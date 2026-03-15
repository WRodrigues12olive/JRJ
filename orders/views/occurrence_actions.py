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
        # Novo comportamento: NÃO mexer na ordem global de todas as paradas.
        # Apenas reposiciona o bloco desta OS (coleta + entregas/devoluções)
        # para o final da rota do motoboy, preservando a OS atual em execução.
        with transaction.atomic():
            # 1) Descobre o grupo (raiz) desta OS
            root_os_local = os_atual.parent_os or os_atual

            # 2) Todas as paradas pendentes do grupo desta OS para este motoboy
            grupo_ids = ServiceOrder.objects.filter(
                Q(id=root_os_local.id) | Q(parent_os=root_os_local)
            ).values_list('id', flat=True)

            paradas_grupo = list(RouteStop.objects.filter(
                motoboy=motoboy_da_parada,
                service_order_id__in=grupo_ids,
                is_completed=False
            ).order_by('stop_type', 'sequence'))

            # Garante que a parada da ocorrência está na lista
            if parada not in paradas_grupo:
                paradas_grupo.append(parada)

            # Ordena de forma que COLETA da OS venha antes das ENTREGAS/DEVOLUCOES da própria OS
            def _ord_key(p):
                prioridade_tipo = 0
                if p.stop_type == 'COLETA':
                    prioridade_tipo = 0
                elif p.stop_type in ['ENTREGA', 'DEVOLUCAO']:
                    prioridade_tipo = 1
                else:
                    prioridade_tipo = 2
                return (prioridade_tipo, p.sequence or 0, p.id)

            paradas_grupo.sort(key=_ord_key)

            # 3) MAIOR sequência entre as paradas que NÃO são desta OS (para não incluir as que vamos reposicionar)
            # Assim a OS que o motoboy já iniciou nunca é ultrapassada pela OS que o despachante acabou de resolver.
            max_seq_global = RouteStop.objects.filter(
                motoboy=motoboy_da_parada,
                is_completed=False,
                sequence__lt=900
            ).exclude(service_order_id__in=grupo_ids).aggregate(Max('sequence'))['sequence__max'] or 0

            # 4) Joga o bloco desta OS para DEPOIS de tudo que já existe
            nova_seq_base = max_seq_global + 1
            for idx, p in enumerate(paradas_grupo):
                is_target = (p.id == parada.id)
                nova_seq = nova_seq_base + idx
                RouteStop.objects.filter(id=p.id).update(
                    sequence=nova_seq,
                    is_failed=False if is_target else p.is_failed,
                    bloqueia_proxima=False if is_target else p.bloqueia_proxima,
                    status=RouteStop.StopStatus.PENDENTE if is_target else p.status,
                    failure_reason="" if is_target else p.failure_reason
                )

            # 5) Se o problema foi na COLETA, limpa a flag de bloqueio das entregas dessa mesma OS
            if parada.stop_type == 'COLETA':
                RouteStop.objects.filter(
                    service_order=parada.service_order,
                    is_completed=False,
                    failure_reason__icontains="Coleta desta OS falhou"
                ).update(is_failed=False, failure_reason="")
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
    """Devolve a OS à fila (desvincula motoboy, reseta paradas e itens)."""
    os_atual = ocorrencia.service_order
    root_os = os_atual.parent_os or os_atual
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))
    root_os.status = 'PENDENTE'
    root_os.motoboy = None
    root_os.operational_notes += f"\n[🔄 VOLTOU À FILA] A OS retornou para Aguardando. Motivo: {ocorrencia.get_causa_display()}."
    root_os.save()
    grouped_orders.exclude(id=root_os.id).update(status='PENDENTE', motoboy=None)
    RouteStop.objects.filter(
        service_order__in=grouped_orders,
        is_completed=False
    ).update(
        motoboy=None,
        is_failed=False,
        failure_reason="",
        status=RouteStop.StopStatus.PENDENTE,
        bloqueia_proxima=False
    )
    OSItem.objects.filter(
        order__in=grouped_orders,
        posse_atual=ocorrencia.motoboy
    ).update(status=OSItem.ItemStatus.NAO_COLETADO, posse_atual=None)
    DispatcherDecision.objects.create(
        occurrence=ocorrencia, acao='VOLTAR_FILA',
        detalhes="Motoboy desvinculado. OS devolvida para a fila Aguardando.", decidido_por=user
    )
    ocorrencia.resolvida = True
    ocorrencia.save()
