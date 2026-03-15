"""
Views do painel de despacho: ocorrências, roteirização, merge/unmerge, atribuição, etc.
"""
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, F, Max, Exists, OuterRef
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from logistics.models import MotoboyProfile
from orders.models import (
    Occurrence,
    DispatcherDecision,
    RouteStop,
    ServiceOrder,
)
from orders.services import transferir_rota_por_acidente

from .occurrence_actions import apply_reagendar, apply_voltar_fila


@login_required
@require_POST
def resolve_occurrence_view(request, occurrence_id):
    """
    Fluxo oficial: processa a decisão do despachante para uma ocorrência (por ID).
    Ações: TRANSFERIR_MOTOBOY, REAGENDAR (com opção de novo endereço), RETORNAR, VOLTAR_FILA.
    A lógica de REAGENDAR e VOLTAR_FILA é compartilhada com resolve_os_problem quando existe ocorrência.
    """
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)

    ocorrencia = get_object_or_404(Occurrence, id=occurrence_id, resolvida=False)
    data = json.loads(request.body)
    acao = data.get('acao')

    os_atual = ocorrencia.service_order
    parada = ocorrencia.parada

    try:
        if acao == DispatcherDecision.Acao.TRANSFERIR_MOTOBOY:
            novo_motoboy_id = data.get('novo_motoboy_id')
            local_encontro = data.get('local_encontro', 'Base da Empresa')
            complemento_transfer = (data.get('complemento_transfer') or '').strip()
            furar_fila = bool(data.get('furar_fila', True))
            transfer_all_cargo = str(data.get('transfer_all_cargo', 'false')).lower() == 'true'

            if not novo_motoboy_id:
                return JsonResponse({'status': 'error', 'message': 'Selecione um motoboy.'}, status=400)

            transferir_rota_por_acidente(
                ocorrencia.id, novo_motoboy_id, local_encontro, request.user, furar_fila, transfer_all_cargo,
                complemento_transfer=complemento_transfer
            )

            return JsonResponse({'status': 'success', 'message': 'Rota transferida com sucesso!'})

        elif acao == DispatcherDecision.Acao.REAGENDAR:
            incluir_novo_endereco = bool(data.get('incluir_novo_endereco'))
            novo_endereco = data.get('novo_endereco') or {}

            # 1. Atualização de endereço (apenas para causa NAO_LOCALIZADO)
            if incluir_novo_endereco:
                if ocorrencia.causa != Occurrence.Causa.NAO_LOCALIZADO:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Novo endereco so pode ser informado para ocorrencia de endereco nao localizado.'
                    }, status=400)
                street = (novo_endereco.get('street') or '').strip()
                city = (novo_endereco.get('city') or '').strip()
                if not street or not city:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Para atualizar o endereco, preencha ao menos Rua e Cidade.'
                    }, status=400)
                number = (novo_endereco.get('number') or '').strip()
                district = (novo_endereco.get('district') or '').strip()
                state = (novo_endereco.get('state') or '').strip().upper()
                cep = (novo_endereco.get('cep') or '').strip()
                complement = (novo_endereco.get('complement') or '').strip()
                if parada.stop_type == RouteStop.StopType.COLLECTION:
                    os_alvo = parada.service_order
                    os_alvo.origin_street = street
                    os_alvo.origin_number = number
                    os_alvo.origin_complement = complement
                    os_alvo.origin_district = district
                    os_alvo.origin_city = city
                    os_alvo.origin_state = state
                    os_alvo.origin_zip_code = cep
                    os_alvo.save(update_fields=[
                        'origin_street', 'origin_number', 'origin_complement',
                        'origin_district', 'origin_city', 'origin_state', 'origin_zip_code'
                    ])
                elif parada.stop_type == RouteStop.StopType.DELIVERY and parada.destination_id:
                    dest = parada.destination
                    dest.destination_street = street
                    dest.destination_number = number
                    dest.destination_complement = complement
                    dest.destination_district = district
                    dest.destination_city = city
                    dest.destination_state = state
                    dest.destination_zip_code = cep
                    dest.save(update_fields=[
                        'destination_street', 'destination_number', 'destination_complement',
                        'destination_district', 'destination_city', 'destination_state', 'destination_zip_code'
                    ])
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Novo endereco so pode ser aplicado em paradas de coleta ou entrega.'
                    }, status=400)

            notes_extra = None
            if incluir_novo_endereco:
                notes_extra = f"\n[ENDERECO ATUALIZADO] Tentativa reativada com novo endereco na parada {parada.get_stop_type_display()}."
            apply_reagendar(ocorrencia, request.user, operational_notes_extra=notes_extra)

        elif acao == DispatcherDecision.Acao.RETORNAR:
            endereco_retorno = data.get('endereco_retorno', 'Base da Empresa')
            complemento_retorno = data.get('complemento_retorno', '')
            is_priority = data.get('is_priority', False)

            # 1. Finaliza a parada que falhou (tira-a da frente)
            parada.is_failed = True
            parada.is_completed = True
            parada.completed_at = timezone.now()
            parada.status = RouteStop.StopStatus.COM_OCORRENCIA
            parada.save()

            # 2. Desbloqueia apenas as paradas pendentes relacionadas a este grupo de OS
            motoboy = ocorrencia.motoboy
            root_os = os_atual.parent_os or os_atual
            grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))
            RouteStop.objects.filter(
                motoboy=motoboy,
                service_order__in=grouped_orders,
                is_completed=False
            ).update(is_failed=False, bloqueia_proxima=False, failure_reason="")

            # 3. Calcula a sequência (Onde a devolução vai entrar)
            if is_priority:
                current_active = motoboy.route_stops.filter(is_completed=False).order_by('sequence').first()
                sequence_to_use = current_active.sequence if current_active else parada.sequence + 1
                motoboy.route_stops.filter(is_completed=False, sequence__gte=sequence_to_use).update(sequence=F('sequence') + 1)
            else:
                ultima = motoboy.route_stops.aggregate(max_seq=Max('sequence'))['max_seq'] or 0
                sequence_to_use = ultima + 1

            # 4. Cria a parada de DEVOLUÇÃO
            devolucao_payload = {
                "service_order": os_atual,
                "motoboy": motoboy,
                "stop_type": 'DEVOLUCAO',
                "sequence": sequence_to_use,
                "custom_address": f"Devolver em: {endereco_retorno}",
                "custom_complement": complemento_retorno,
                "status": 'PENDENTE',
                "bloqueia_proxima": False
            }
            if parada.stop_type == 'ENTREGA' and parada.destination:
                devolucao_payload['destination'] = parada.destination
            
            RouteStop.objects.create(**devolucao_payload)

            # 5. Resolve a ocorrência e atualiza logs
            DispatcherDecision.objects.create(
                occurrence=ocorrencia, acao=acao,
                detalhes=f"Devolução agendada para: {endereco_retorno} (Prioridade: {is_priority})",
                decidido_por=request.user
            )

            ocorrencia.resolvida = True
            ocorrencia.save()

            root_os = os_atual.parent_os or os_atual
            grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))
            grouped_orders.update(status='COLETADO')

        elif acao == 'VOLTAR_FILA':
            apply_voltar_fila(ocorrencia, request.user)

        else:
            return JsonResponse({'status': 'error', 'message': 'Ação não reconhecida.'}, status=400)

        return JsonResponse({'status': 'success'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
@require_POST
def resolve_os_problem(request, os_id):
    """
    Resolve problema da OS (Reativar ou Desvincular).
    Fluxo unificado: se existir ocorrência não resolvida para esta OS, delega para
    apply_reagendar / apply_voltar_fila (mesma lógica de resolve_occurrence_view).
    Caso contrário, aplica o comportamento legado (sem vínculo com Occurrence).
    """
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)

    os = get_object_or_404(ServiceOrder, id=os_id)
    data = json.loads(request.body)
    action = data.get('action', 'reactivate')

    root_os = os.parent_os or os
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))

    # Unificado: se houver ocorrência não resolvida, usa o mesmo fluxo que resolve_occurrence
    ocorrencia = Occurrence.objects.filter(
        service_order__in=grouped_orders,
        resolvida=False
    ).order_by('-criado_em').first()

    if ocorrencia:
        if action == 'reactivate':
            apply_reagendar(ocorrencia, request.user)
            return JsonResponse({'status': 'success'})
        if action == 'unassign':
            apply_voltar_fila(ocorrencia, request.user)
            return JsonResponse({'status': 'success'})

    # Legado: sem ocorrência (OS em problema antiga ou edge case)
    if action == 'reactivate':
        failed_stop_ids = list(
            RouteStop.objects.filter(
                service_order__in=grouped_orders,
                is_completed=False,
                is_failed=True
            ).values_list('id', flat=True)
        )
        group_stops = RouteStop.objects.filter(service_order__in=grouped_orders)
        new_status = 'COLETADO' if group_stops.filter(stop_type='COLETA', is_completed=True).exists() else 'ACEITO'
        grouped_orders.update(status=new_status)
        root_os.operational_notes += f"\n[✅ RESOLVIDO] Ocorrência ignorada e rota reativada por {request.user.first_name}."
        RouteStop.objects.filter(
            service_order__in=grouped_orders, is_completed=False, is_failed=True
        ).update(is_failed=False, failure_reason="")
        for stop in RouteStop.objects.filter(id__in=failed_stop_ids).select_related('motoboy'):
            if not stop.motoboy_id or stop.is_completed:
                continue
            outras_pendentes = RouteStop.objects.filter(
                motoboy=stop.motoboy, is_completed=False
            ).exclude(id=stop.id)
            if outras_pendentes.exists():
                ultima_seq = outras_pendentes.aggregate(max_seq=Max('sequence'))['max_seq'] or 0
                stop.sequence = ultima_seq + 1
                stop.save(update_fields=['sequence'])
    elif action == 'unassign':
        grouped_orders.update(status='PENDENTE', motoboy=None)
        RouteStop.objects.filter(
            service_order__in=grouped_orders, is_completed=False
        ).update(motoboy=None, is_failed=False, failure_reason="")
        root_os.operational_notes += f"\n[🔄 RETORNOU] Grupo removido do motoboy e voltou para a fila por {request.user.first_name}."

    root_os.save()
    return JsonResponse({'status': 'success'})


@login_required
def dispatch_dashboard_view(request):
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return redirect('root')

    pending_orders = ServiceOrder.objects.filter(
        Q(status='PENDENTE') | Q(status='OCORRENCIA', motoboy__isnull=True)
    ).order_by('-priority', 'created_at')

    motoboys = MotoboyProfile.objects.all()

    motoboy_data = []
    for mb in motoboys:
        last_seen = cache.get(f'seen_{mb.user.id}')
        is_absent = getattr(mb, 'is_absent', False)
        is_online = mb.is_available and bool(last_seen) and not is_absent

        ativas = mb.route_stops.filter(
            is_completed=False
        ).exclude(
            failure_reason__icontains='[AGUARDANDO SOCORRO]'
        ).order_by('sequence')

        aguardando_socorro = mb.route_stops.filter(
            is_completed=False,
            failure_reason__icontains='[AGUARDANDO SOCORRO]'
        ).order_by('sequence')

        motoboy_data.append({
            'profile': mb,
            'is_online': is_online,
            'is_absent': is_absent,
            'load': ativas.count() + aguardando_socorro.count(),
            'max_load': 10,
            'active_stops': ativas,
            'waiting_rescue_stops': aguardando_socorro,
        })

    motoboy_data.sort(key=lambda x: x['is_online'], reverse=True)

    total_ativas = sum(mb['load'] for mb in motoboy_data)
    total_ocorrencias = ServiceOrder.objects.filter(status='OCORRENCIA').count()

    context = {
        'pending_orders': pending_orders,
        'motoboy_data': motoboy_data,
        'total_ativas': total_ativas,
        'total_ocorrencias': total_ocorrencias,
        'now': timezone.now(),
    }
    context['ocorrencias_pendentes'] = Occurrence.objects.filter(resolvida=False).annotate(
        has_extra_cargo=Exists(
            ServiceOrder.objects.filter(
                motoboy=OuterRef('motoboy_id'),
                status='COLETADO'
            ).exclude(
                id=OuterRef('service_order_id')
            ).exclude(
                parent_os=OuterRef('service_order_id')
            )
        )
    ).order_by('-urgencia', '-criado_em')

    return render(request, 'orders/dispatch_panel.html', context)


@login_required
def get_route_stops(request, os_id):
    """Retorna a rota de uma OS em JSON para montar a timeline no Modal"""
    os_alvo = get_object_or_404(ServiceOrder, id=os_id)
    stops = RouteStop.objects.filter(
        Q(service_order=os_alvo) | Q(service_order__parent_os=os_alvo)
    ).order_by('sequence')

    data = []
    for stop in stops:
        complemento = ""

        if stop.stop_type == 'COLETA':
            location = stop.service_order.origin_name
            address = f"{stop.service_order.origin_street}, {stop.service_order.origin_number} - {stop.service_order.origin_district}"
            complemento = stop.service_order.origin_complement
            valor = 0.00

        elif stop.stop_type in ['DEVOLUCAO', 'TRANSFERENCIA']:
            location = "Ponto de Transferência" if stop.stop_type == 'TRANSFERENCIA' else "Devolução"
            address = stop.custom_address.replace("Devolver em: ", "") if stop.custom_address else "Endereço não informado"
            complemento = stop.custom_complement if stop.custom_complement else ""
            valor = float(stop.destination.delivery_value) if stop.destination and stop.destination.delivery_value else 0.00

        else:
            location = stop.destination.destination_name if stop.destination else "Indefinido"
            address = f"{stop.destination.destination_street}, {stop.destination.destination_number} - {stop.destination.destination_district}" if stop.destination else ""
            complemento = stop.destination.destination_complement if stop.destination else ""
            valor = float(stop.destination.delivery_value) if stop.destination and stop.destination.delivery_value else 0.00

        data.append({
            'id': stop.id,
            'type': stop.stop_type,
            'sequence': stop.sequence,
            'location': location,
            'address': address,
            'complement': complemento,
            'value': valor,
        })

    return JsonResponse({'status': 'success', 'stops': data})


@login_required
@require_POST
def merge_os_view(request):
    """Funde duas Ordens de Serviço Visualmente (A Origem vira Filha do Destino)"""
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)

    data = json.loads(request.body)
    source_id = data.get('source_os')
    target_id = data.get('target_os')

    if source_id == target_id:
        return JsonResponse({'status': 'error', 'message': 'Não é possível mesclar uma OS com ela mesma.'})

    source_os = get_object_or_404(ServiceOrder, id=source_id)
    target_os = get_object_or_404(ServiceOrder, id=target_id)

    if source_os.status != 'PENDENTE' or target_os.status != 'PENDENTE':
        return JsonResponse({'status': 'error', 'message': 'Apenas OS PENDENTES podem ser mescladas.'})

    with transaction.atomic():
        source_os.parent_os = target_os
        source_os.status = 'AGRUPADO'
        source_os.operational_notes += f"\n[AGRUPADA] Viajando junto com a OS {target_os.os_number}."
        source_os.save()

        last_seq = target_os.stops.count()
        for stop in source_os.stops.order_by('sequence'):
            last_seq += 1
            stop.sequence = last_seq
            stop.save()

        target_os.operational_notes += f"\n[GRUPO] Levando também as entregas da OS {source_os.os_number}."
        target_os.is_multiple_delivery = True
        target_os.save()

    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def unmerge_os_view(request):
    """
    Desfaz a mesclagem de uma OS filha, voltando ela para o estado independente (PENDENTE).
    Somente OS que já foram mescladas (status=AGRUPADO e com parent_os definido) podem ser desfeitas.
    """
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)

    data = json.loads(request.body or "{}")
    child_id = data.get('child_os')

    if not child_id:
        return JsonResponse({'status': 'error', 'message': 'OS filha não informada.'}, status=400)

    with transaction.atomic():
        child_os = get_object_or_404(ServiceOrder.objects.select_for_update(), id=child_id)

        if not child_os.parent_os or child_os.status != 'AGRUPADO':
            return JsonResponse({'status': 'error', 'message': 'Esta OS não está mesclada ou já foi atribuída.'}, status=400)

        parent = child_os.parent_os

        if parent.status != 'PENDENTE':
            return JsonResponse({
                'status': 'error',
                'message': 'A OS principal já está em trânsito! A mercadoria já se encontra com o motoboy.'
            }, status=400)

        child_os.parent_os = None
        child_os.status = 'PENDENTE'

        for marker in ["[AGRUPADA]", "[MESCLADA]"]:
            if child_os.operational_notes and marker in child_os.operational_notes:
                child_os.operational_notes = child_os.operational_notes.replace(marker, "").strip()

        child_os.save()

        if parent:
            if parent.operational_notes and "[GRUPO]" in parent.operational_notes:
                parent.operational_notes += f"\n[DESFEITO] OS {child_os.os_number} removida do grupo."

            if not parent.child_orders.exists():
                parent.is_multiple_delivery = False

            parent.save()

    return JsonResponse({'status': 'success'})


@login_required
def assign_motoboy_view(request, os_id):
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return redirect('root')

    from django.contrib import messages

    if request.method == 'POST':
        motoboy_id = request.POST.get('motoboy_id')

        with transaction.atomic():
            os = get_object_or_404(ServiceOrder.objects.select_for_update(), id=os_id)

            if os.status != 'PENDENTE':
                messages.error(request, f"A OS #{os.os_number} já não está na fila. Foi atribuída a outro motoboy ou cancelada.")
                return redirect('dispatch_dashboard')

            motoboy = get_object_or_404(MotoboyProfile, id=motoboy_id)

            os.motoboy = motoboy
            os.status = 'ACEITO'
            os.save()

            child_orders = ServiceOrder.objects.filter(parent_os=os)
            child_orders.update(motoboy=motoboy, status='ACEITO')

            # Regra: mais antigas primeiro — nova OS sempre no FINAL da rota (maior sequência)
            last_seq = RouteStop.objects.filter(
                motoboy=motoboy, is_completed=False, sequence__lt=900
            ).aggregate(Max('sequence'))['sequence__max'] or 0

            stops = RouteStop.objects.filter(
                Q(service_order=os) | Q(service_order__parent_os=os)
            ).order_by('sequence')

            for stop in stops:
                last_seq += 1
                stop.motoboy = motoboy
                stop.sequence = last_seq
                stop.save()

            messages.success(request, f"Roteiro da OS #{os.os_number} adicionado à rota de {motoboy.user.first_name}!")

    return redirect('dispatch_dashboard')


@login_required
def reorder_stops_view(request):
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método inválido.'}, status=405)

    data = json.loads(request.body or "{}")
    raw_ids = data.get('stops', [])

    stop_ids = []
    for sid in raw_ids:
        try:
            stop_ids.append(int(sid))
        except (TypeError, ValueError):
            continue

    if not stop_ids:
        return JsonResponse({'status': 'error', 'message': 'Lista de paradas vazia.'}, status=400)

    stops_meta = list(RouteStop.objects.filter(id__in=stop_ids).values('id', 'stop_type', 'service_order_id'))
    id_to_meta = {s['id']: s for s in stops_meta}

    stop_ids = [sid for sid in stop_ids if sid in id_to_meta]
    if not stop_ids:
        return JsonResponse({'status': 'error', 'message': 'Nenhuma parada válida encontrada.'}, status=400)

    os_coleta_seen = set()
    for sid in stop_ids:
        meta = id_to_meta[sid]
        os_id = meta['service_order_id']
        stype = meta['stop_type']

        if stype == 'COLETA':
            os_coleta_seen.add(os_id)
        elif stype in ['ENTREGA', 'DEVOLUCAO']:
            if os_id not in os_coleta_seen:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Ordem inválida! Uma Entrega ou Devolução não pode ocorrer antes da Coleta da sua respectiva OS.'
                }, status=400)

    for index, stop_id in enumerate(stop_ids):
        RouteStop.objects.filter(id=stop_id).update(sequence=index + 1)

    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def transfer_route_view(request, os_id):
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)

    data = json.loads(request.body)
    new_motoboy_id = data.get('new_motoboy_id')
    transfer_address = (data.get('transfer_address') or '').strip()
    transfer_complement = (data.get('transfer_complement') or '').strip()

    os_obj = get_object_or_404(ServiceOrder, id=os_id)
    os_root = os_obj.parent_os or os_obj
    grouped_orders = ServiceOrder.objects.filter(Q(id=os_root.id) | Q(parent_os=os_root))
    new_motoboy = get_object_or_404(MotoboyProfile, id=new_motoboy_id)

    with transaction.atomic():
        group_stops = RouteStop.objects.filter(service_order__in=grouped_orders)
        is_collected = group_stops.filter(stop_type='COLETA', is_completed=True).exists()

        first_pending = RouteStop.objects.filter(
            service_order__in=grouped_orders,
            is_completed=False
        ).exclude(
            failure_reason__icontains="[AGUARDANDO SOCORRO]"
        ).order_by('sequence').first()

        if not first_pending:
            return JsonResponse({'status': 'error', 'message': 'Nenhuma parada para transferir.'})

        old_motoboy = first_pending.motoboy

        if old_motoboy and old_motoboy != new_motoboy:
            RouteStop.objects.create(
                service_order=os_root,
                motoboy=old_motoboy,
                stop_type='TRANSFERENCIA',
                sequence=99,
                failure_reason="[AGUARDANDO SOCORRO] Veículo avariado."
            )

        if not is_collected:
            pending_real_stops = RouteStop.objects.filter(
                service_order__in=grouped_orders, is_completed=False
            ).exclude(
                failure_reason__icontains="[AGUARDANDO SOCORRO]"
            ).exclude(
                failure_reason__icontains="Encontro:"
            )

            pending_real_stops.update(motoboy=new_motoboy)

            for stop in pending_real_stops:
                if stop.failure_reason and ("avariado" in stop.failure_reason or "OCORRÊNCIA" in stop.failure_reason):
                    stop.failure_reason = ""
                    stop.save()

            new_status = 'ACEITO'
            grouped_orders.update(motoboy=new_motoboy, status=new_status)

            os_root.status = new_status
            os_root.motoboy = new_motoboy
            os_root.operational_notes += (
                f"\n[🚨 SOCORRO] Veículo avariado ANTES da coleta. "
                f"OS reatribuída para {new_motoboy.user.first_name} (coleta no endereço original)."
            )
            os_root.save()

            return JsonResponse({'status': 'success'})

        if not transfer_address:
            return JsonResponse({
                'status': 'error',
                'message': 'Esta OS já foi coletada. Informe o local de encontro para transferir a carga.'
            }, status=400)

        seq_transf = first_pending.sequence
        RouteStop.objects.filter(
            service_order__in=grouped_orders, is_completed=False
        ).exclude(failure_reason__icontains="[AGUARDANDO SOCORRO]").update(sequence=F('sequence') + 1)

        RouteStop.objects.create(
            service_order=os_root, motoboy=new_motoboy, stop_type='TRANSFERENCIA',
            sequence=seq_transf, custom_address=transfer_address,
            custom_complement=transfer_complement
        )

        pending_real_stops = RouteStop.objects.filter(
            service_order__in=grouped_orders, is_completed=False
        ).exclude(failure_reason__icontains="[AGUARDANDO SOCORRO]").exclude(stop_type='TRANSFERENCIA')

        pending_real_stops.update(motoboy=new_motoboy)

        for stop in pending_real_stops:
            if stop.failure_reason and ("avariado" in stop.failure_reason or "OCORRÊNCIA" in stop.failure_reason):
                stop.failure_reason = ""
                stop.save()

        new_status = 'COLETADO'
        grouped_orders.update(motoboy=new_motoboy, status=new_status)

        os_root.status = new_status
        os_root.motoboy = new_motoboy
        os_root.operational_notes += f"\n[🚨 SOCORRO] Carga transferida para {new_motoboy.user.first_name}. Ponto de encontro: {transfer_address}"
        os_root.save()

    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def create_return_view(request, os_id):
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error'}, status=403)

    data = json.loads(request.body)
    return_address = data.get('return_address', 'Base da Transportadora')
    is_priority = data.get('is_priority', False)

    root_os = get_object_or_404(ServiceOrder, id=os_id)
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))

    with transaction.atomic():
        motoboy = root_os.motoboy

        active_stop = motoboy.route_stops.filter(service_order__in=grouped_orders, is_completed=False).order_by('sequence').first()
        if active_stop and active_stop.is_failed:
            active_stop.is_completed = True
            active_stop.completed_at = timezone.now()
            active_stop.save()

        sequence_to_use = 99
        if motoboy:
            if is_priority:
                current_active = motoboy.route_stops.filter(is_completed=False).order_by('sequence').first()
                if current_active:
                    sequence_to_use = current_active.sequence + 1
                    motoboy.route_stops.filter(
                        is_completed=False, sequence__gte=sequence_to_use
                    ).update(sequence=F('sequence') + 1)
                else:
                    sequence_to_use = motoboy.route_stops.count() + 1
            else:
                sequence_to_use = motoboy.route_stops.count() + 1

        RouteStop.objects.create(
            service_order=root_os,
            motoboy=motoboy,
            stop_type='DEVOLUCAO',
            sequence=sequence_to_use,
            custom_address=return_address
        )

        tipo_log = "PRIORITÁRIA" if is_priority else "NORMAL"
        root_os.operational_notes += f"\n[🔄 DEVOLUÇÃO {tipo_log}] Agendada devolução para {return_address}."

        group_stops = RouteStop.objects.filter(service_order__in=grouped_orders)
        if group_stops.filter(stop_type='COLETA', is_completed=True).exists():
            root_os.status = 'COLETADO'
        else:
            root_os.status = 'ACEITO'

        root_os.save()

    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def update_stop_value_view(request, stop_id):
    if request.user.type != 'DISPATCHER' and not request.user.is_superuser:
        return JsonResponse({'status': 'error'}, status=403)

    stop = get_object_or_404(RouteStop, id=stop_id)
    if stop.stop_type == 'ENTREGA' and stop.destination:
        data = json.loads(request.body)

        novo_valor = str(data.get('value', '0.00'))
        val_final = max(Decimal('0.00'), Decimal(novo_valor)) if novo_valor else Decimal('0.00')

        stop.destination.delivery_value = val_final
        stop.destination.save()
        return JsonResponse({'status': 'success'})

    return JsonResponse({'status': 'error', 'message': 'Apenas paradas de entrega possuem valor.'}, status=400)
