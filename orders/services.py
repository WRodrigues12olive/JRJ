from django.db import transaction, models
from django.db.models import Q, Value, Max, F
from django.db.models.functions import Concat
from .models import ServiceOrder, RouteStop, OSItem, Occurrence, DispatcherDecision

@transaction.atomic
def transferir_rota_por_acidente(ocorrencia_id, novo_motoboy_id, local_transferencia_str, despachante_user, furar_fila=False, transfer_all_cargo=False):
    ocorrencia = Occurrence.objects.select_for_update().get(id=ocorrencia_id)
    os_atual = ocorrencia.service_order
    motoboy_antigo = ocorrencia.motoboy
    
    if ocorrencia.resolvida:
        raise ValueError("Esta ocorrência já foi resolvida.")

    # 1. Tira o motoboy acidentado de circulação
    motoboy_antigo.is_available = False
    motoboy_antigo.save()

    # Define a OS "Mãe" do acidente (a que vai receber as outras)
    root_os = os_atual.parent_os or os_atual

    # 👇 --- A MÁGICA DA MESCLA: TRANSFORMA AS CARGAS EXTRAS EM FILHAS DA OS ATUAL --- 👇
    if transfer_all_cargo:
        outras_os_coletadas = ServiceOrder.objects.filter(
            motoboy=motoboy_antigo,
            status='COLETADO'
        ).exclude(
            Q(id=root_os.id) | Q(parent_os=root_os)
        )
        
        if outras_os_coletadas.exists():
            for os_extra in outras_os_coletadas:
                # Encontra a raiz da carga extra
                root_extra = os_extra.parent_os or os_extra

                # Transforma a raiz extra numa FILHA da OS do acidente
                root_extra.parent_os = root_os
                root_extra.status = 'AGRUPADO'
                root_extra.operational_notes += f"\n[AGRUPADA NO RESGATE] Mesclada com a OS principal {root_os.os_number}."
                root_extra.save()

                # Se a extra já tinha filhas, achata a árvore passando elas para a OS do acidente
                ServiceOrder.objects.filter(parent_os=root_extra).update(parent_os=root_os)

            root_os.is_multiple_delivery = True
            root_os.operational_notes += f"\n[GRUPO DE RESGATE] Absorveu cargas extras que estavam retidas no baú."
            root_os.save()
    # 👆 ----------------------------------------------------------------------------- 👆

    # 2. Agora que mesclamos tudo, o nosso grupo de trabalho é o pacote completo!
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))

    # 3. Devolve para a fila APENAS as OS que não foram coletadas e não entraram na mescla
    outras_os_pendentes = ServiceOrder.objects.filter(
        motoboy=motoboy_antigo, 
        status__in=['PENDENTE', 'ACEITO']
    ).exclude(
        id__in=grouped_orders.values_list('id', flat=True)
    )
    RouteStop.objects.filter(service_order__in=outras_os_pendentes, is_completed=False).update(motoboy=None, status='PENDENTE')
    outras_os_pendentes.update(motoboy=None, status='PENDENTE')

    # Registra a decisão
    DispatcherDecision.objects.create(
        occurrence=ocorrencia,
        acao=DispatcherDecision.Acao.TRANSFERIR_MOTOBOY,
        detalhes=f"Transferido para ID {novo_motoboy_id}. Urgência: {furar_fila}. Baú inteiro: {transfer_all_cargo}. Local: {local_transferencia_str}",
        decidido_por=despachante_user
    )

    # Lógica de Sequência para o novo motoboy
    def calcular_sequencia_novo_motoboy():
        if furar_fila:
            RouteStop.objects.filter(motoboy_id=novo_motoboy_id, is_completed=False).update(sequence=F('sequence') + 10)
            return 1
        else:
            ultima = RouteStop.objects.filter(motoboy_id=novo_motoboy_id).aggregate(Max('sequence'))['sequence__max'] or 0
            return ultima + 1

    seq_transferencia = calcular_sequencia_novo_motoboy()

    # O sistema confia na parada de COLETA (Verificamos se QUALQUER OS do grupo gigante já foi coletada)
    tem_itens_na_bag = RouteStop.objects.filter(
        service_order__in=grouped_orders, 
        stop_type='COLETA', 
        is_completed=True
    ).exists()
    
    # Congela a lista de paradas do grupo gigante ANTES de criarmos as paradas de transferência
    paradas_pendentes = list(RouteStop.objects.filter(
        service_order__in=grouped_orders, 
        motoboy=motoboy_antigo, 
        is_completed=False
    ).order_by('sequence'))

    if not tem_itens_na_bag:
        # --- TRANSFERÊNCIA LIMPA (Acidente ANTES de pegar o pacote na loja) ---
        for index, p in enumerate(paradas_pendentes):
            p.sequence = seq_transferencia + index
            p.motoboy_id = novo_motoboy_id
            p.status = RouteStop.StopStatus.PENDENTE
            p.is_failed = False
            p.failure_reason = ""
            p.bloqueia_proxima = False
            p.save()
            
        root_os.operational_notes += f"\n[TRANSFERÊNCIA LIMPA] Rota repassada para outro técnico antes da coleta."
        novo_status_os = 'ACEITO'
        
    else:
        # --- TRANSFERÊNCIA COM CARGA (O Baú está cheio) ---
        
        # Cria UMA ÚNICA parada de aviso para o motoboy antigo
        RouteStop.objects.create(
            service_order=root_os,
            motoboy=motoboy_antigo,
            stop_type='TRANSFERENCIA',
            sequence=1,
            status=RouteStop.StopStatus.PENDENTE,
            custom_address=f"AGUARDE O RESGATE AQUI: {local_transferencia_str}", 
            bloqueia_proxima=True
        )

        # Passa os destinos do grupo gigante para o novo motoboy
        for index, p in enumerate(paradas_pendentes):
            p.sequence = seq_transferencia + index + 1
            p.motoboy_id = novo_motoboy_id
            p.status = RouteStop.StopStatus.PENDENTE
            p.is_failed = False
            p.failure_reason = ""
            p.bloqueia_proxima = False
            p.save()

        # Cria UMA ÚNICA parada de resgate para o novo motoboy
        RouteStop.objects.create(
            service_order=root_os,
            motoboy_id=novo_motoboy_id,
            stop_type='TRANSFERENCIA',
            sequence=seq_transferencia,
            custom_address=f"Resgatar carga(s) de colega acidentado: {local_transferencia_str}", # ✅ USAR O NOVO CAMPO
            status=RouteStop.StopStatus.PENDENTE,
            bloqueia_proxima=True
        )

        # Atualiza TODOS os itens de TODAS as OS mescladas
        OSItem.objects.filter(
            order__in=grouped_orders, 
            posse_atual=motoboy_antigo, 
            status=OSItem.ItemStatus.COLETADO
        ).update(
            status=OSItem.ItemStatus.TRANSFERIDO,
            item_notes=Concat(
                models.F('item_notes'), 
                Value(f"\n[RESGATE CONJUNTO] Transferido no local: {local_transferencia_str}")
            )
        )
        novo_status_os = 'COLETADO'

    ocorrencia.resolvida = True
    ocorrencia.save()

    # Atualiza tudo para o novo motoboy. As filhas ficam 'AGRUPADO' e a Mãe fica 'COLETADO'
    grouped_orders.exclude(id=root_os.id).update(motoboy_id=novo_motoboy_id, status='AGRUPADO')
    root_os.status = novo_status_os
    root_os.motoboy_id = novo_motoboy_id
    root_os.save()
    
    return True