"""
Lógica compartilhada de resolução de ocorrências (reagendar e voltar à fila).
Usado por resolve_occurrence_view e resolve_os_problem.
"""
from django.db import transaction
from django.db.models import Q, F, Max

from orders.models import RouteStop, ServiceOrder, OSItem, Occurrence, DispatcherDecision


def apply_reagendar(ocorrencia, user, operational_notes_extra=None):
    """
    Reativa a parada da ocorrência (reordena na rota, limpa falha, atualiza OS).
    """
    parada = ocorrencia.parada
    os_atual = ocorrencia.service_order
    motoboy_da_parada = parada.motoboy

    if motoboy_da_parada:
        with transaction.atomic():
            if parada.stop_type == 'COLETA':
                # Pega as entregas/devoluções que dependem EXCLUSIVAMENTE desta coleta
                paradas_filhas = list(RouteStop.objects.filter(
                    service_order=os_atual,
                    motoboy=motoboy_da_parada,
                    is_completed=False
                ).exclude(id=parada.id).order_by('sequence'))
                
                # Lista de IDs que vamos mover para o fim (a coleta + as suas filhas)
                ids_para_mover = [parada.id] + [p.id for p in paradas_filhas]
                
                # Descobre qual é a última sequência das OUTRAS paradas do motoboy (para não sobrepor)
                outras_paradas = RouteStop.objects.filter(
                    motoboy=motoboy_da_parada,
                    is_completed=False
                ).exclude(id__in=ids_para_mover)
                
                nova_seq = (outras_paradas.aggregate(Max('sequence'))['sequence__max'] or 0) + 1
                
                # 1. Joga a COLETA para o fim
                RouteStop.objects.filter(id=parada.id).update(
                    sequence=nova_seq,
                    is_failed=False,
                    bloqueia_proxima=False,
                    status=RouteStop.StopStatus.PENDENTE,
                    failure_reason=""
                )
                
                # 2. Joga as entregas derivadas dela LOGO ABAIXO no fim
                for p_filha in paradas_filhas:
                    nova_seq += 1
                    RouteStop.objects.filter(id=p_filha.id).update(sequence=nova_seq)

                # Destrava o alerta em cascata
                RouteStop.objects.filter(
                    service_order=os_atual,
                    is_completed=False,
                    failure_reason__icontains="Coleta desta OS falhou"
                ).update(is_failed=False, failure_reason="")

            else:
                # Se não for Coleta (ex: Entrega que o cliente não atendeu), joga só ela pro final
                outras_paradas = RouteStop.objects.filter(
                    motoboy=motoboy_da_parada,
                    is_completed=False
                ).exclude(id=parada.id)
                
                nova_seq = (outras_paradas.aggregate(Max('sequence'))['sequence__max'] or 0) + 1
                
                RouteStop.objects.filter(id=parada.id).update(
                    sequence=nova_seq,
                    is_failed=False,
                    bloqueia_proxima=False,
                    status=RouteStop.StopStatus.PENDENTE,
                    failure_reason=""
                )
    else:
        parada.is_failed = False
        parada.bloqueia_proxima = False
        parada.status = RouteStop.StopStatus.PENDENTE
        parada.failure_reason = ""
        parada.save()
        if parada.stop_type == 'COLETA':
            RouteStop.objects.filter(
                service_order=parada.service_order,
                is_completed=False,
                failure_reason__icontains="Coleta desta OS falhou"
            ).update(is_failed=False, failure_reason="")

    root_os = os_atual.parent_os or os_atual
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))
    group_stops = RouteStop.objects.filter(service_order__in=grouped_orders)
    new_status = 'COLETADO' if group_stops.filter(stop_type='COLETA', is_completed=True).exists() else 'ACEITO'
    grouped_orders.update(status=new_status)
    if operational_notes_extra:
        root_os.operational_notes += operational_notes_extra
        root_os.save(update_fields=['operational_notes'])
    DispatcherDecision.objects.create(
        occurrence=ocorrencia, acao=DispatcherDecision.Acao.REAGENDAR,
        detalhes="O despachante mandou re-tentar ou ignorar o bloqueio.", decidido_por=user
    )
    ocorrencia.resolvida = True
    ocorrencia.save()


def apply_voltar_fila(ocorrencia, user):
    """Devolve APENAS a OS que falhou à fila e desmembra se estiver agrupada."""
    os_alvo = ocorrencia.service_order
    parada = ocorrencia.parada

    # 1. Trava de Segurança Máxima: Só permite voltar para fila se for COLETA
    if parada.stop_type != 'COLETA':
        # Se um despachante tentar forçar (burlando o HTML), o sistema converte para "Retornar Base"
        ocorrencia.resolvida = True
        ocorrencia.save()
        return

    with transaction.atomic():
        # 2. Desmembramento Inteligente
        if os_alvo.parent_os:
            # Se for a OS 02 (filha), apenas cortamos o laço com a mãe (OS 01)
            os_alvo.parent_os = None
        else:
            # Se for a OS 01 (mãe) que falhou, temos que promover uma das filhas a nova mãe
            filhas = list(ServiceOrder.objects.filter(parent_os=os_alvo))
            if filhas:
                nova_mae = filhas.pop(0) # Pega a primeira filha
                nova_mae.parent_os = None
                nova_mae.save()
                # Atualiza as outras filhas para apontarem para a nova mãe
                for f in filhas:
                    f.parent_os = nova_mae
                    f.save()

        # 3. Reseta APENAS a OS que falhou
        os_alvo.status = 'PENDENTE'
        os_alvo.motoboy = None
        os_alvo.operational_notes += f"\n[🔄 VOLTOU À FILA] Coleta falhou. A OS retornou para Aguardando. Motivo: {ocorrencia.get_causa_display()}."
        os_alvo.save()

        # 4. Reseta APENAS as paradas DESTA OS
        RouteStop.objects.filter(
            service_order=os_alvo,
            is_completed=False
        ).update(
            motoboy=None,
            is_failed=False,
            failure_reason="",
            status=RouteStop.StopStatus.PENDENTE,
            bloqueia_proxima=False
        )

        # 5. Reseta os itens DESTA OS
        OSItem.objects.filter(
            order=os_alvo,
            posse_atual=ocorrencia.motoboy
        ).update(status=OSItem.ItemStatus.NAO_COLETADO, posse_atual=None)

        DispatcherDecision.objects.create(
            occurrence=ocorrencia, acao='VOLTAR_FILA',
            detalhes="Coleta com problema. OS desmembrada e devolvida para a fila individualmente.", decidido_por=user
        )
        ocorrencia.resolvida = True
        ocorrencia.save()