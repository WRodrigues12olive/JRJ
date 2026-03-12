"""
Views do motoboy: tarefas, perfil, heartbeat, presença, reportar problema, conserto de veículo.
"""
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from logistics.models import MotoboyProfile
from logistics.validators import validate_cnh, validate_plate, clean_cnh, clean_plate
from orders.models import (
    RouteStop,
    ServiceOrder,
    OSItem,
    ItemDistribution,
    Occurrence,
)

from django.contrib import messages


@login_required
def motoboy_tasks_view(request):
    if request.user.type != 'MOTOBOY':
        return redirect('root')

    try:
        perfil = request.user.motoboy_profile
    except Exception:
        perfil = MotoboyProfile.objects.create(
            user=request.user, vehicle_plate="Pendente",
            cnh_number=f"Pendente_{request.user.id}", category='TELE', is_available=False
        )

    if not perfil.cnh_number or 'Pendente' in perfil.cnh_number or not perfil.vehicle_plate or 'Pendente' in perfil.vehicle_plate:
        return redirect('motoboy_profile')

    pending_os_ids = RouteStop.objects.filter(
        motoboy=perfil,
        is_completed=False
    ).values_list('service_order_id', flat=True)

    ativas_qs = ServiceOrder.objects.filter(
        Q(id__in=pending_os_ids) | Q(child_orders__id__in=pending_os_ids),
        status__in=['ACEITO', 'COLETADO', 'OCORRENCIA', 'PROBLEM'],
        parent_os__isnull=True
    ).distinct().order_by('created_at')

    proxima_parada_global = RouteStop.objects.filter(
        motoboy=perfil,
        is_completed=False
    ).exclude(sequence=999).order_by('sequence').first()

    os_em_execucao_id = proxima_parada_global.service_order.id if proxima_parada_global else None

    ativas_data = []
    for os in ativas_qs:
        stops = RouteStop.objects.filter(
            (Q(service_order=os) | Q(service_order__parent_os=os)),
            motoboy=perfil
        ).order_by('sequence')

        filhas = os.child_orders.all()

        ta_pausada = not stops.filter(is_completed=False).exclude(sequence=999).exists()

        ativas_data.append({
            'os': os,
            'stops': stops,
            'has_children': filhas.exists(),
            'child_numbers': [f.os_number for f in filhas],
            'ta_pausada': ta_pausada,
            'eh_a_atual': (os.id == os_em_execucao_id)
        })

    ativas_data.sort(key=lambda x: (x['ta_pausada'], not x['eh_a_atual'], x['os'].created_at))
    hoje_local = timezone.localtime(timezone.now()).date()
    
    # --- CORREÇÃO AQUI: ADICIONADO is_failed=False ---
    # 1. Busca paradas concluídas com SUCESSO absoluto (Entregas e Devoluções)
    concluidas_qs = RouteStop.objects.filter(
        motoboy=perfil,
        stop_type__in=['ENTREGA', 'DEVOLUCAO'],
        is_completed=True,
        is_failed=False,  # Impede de contabilizar quando o despachante encerra a falha
        completed_at__date=hoje_local
    ).select_related('destination', 'service_order').prefetch_related('service_order__destinations')

    # 2. Busca tentativas que falharam, mas que geraram ocorrência (exceto Acidente)
    ocorrencias_qs = Occurrence.objects.filter(
        motoboy=perfil,
        parada__stop_type__in=['ENTREGA', 'DEVOLUCAO'],
        criado_em__date=hoje_local
    ).exclude(causa='ACIDENTE').select_related('parada__destination', 'parada__service_order').prefetch_related('parada__service_order__destinations')

    valor_bruto_dia = Decimal('0.00')
    entregas_concluidas_hoje = 0

    # Soma os valores das entregas/devoluções bem sucedidas
    for stop in concluidas_qs:
        entregas_concluidas_hoje += 1
        if stop.destination:
            valor_bruto_dia += stop.destination.delivery_value or Decimal('0.00')
        elif stop.stop_type == 'DEVOLUCAO':
            dest = stop.service_order.destinations.first()
            if dest:
                valor_bruto_dia += dest.delivery_value or Decimal('0.00')

    # Soma os valores das tentativas válidas (ocorrências reportadas no local)
    for oc in ocorrencias_qs:
        entregas_concluidas_hoje += 1
        stop = oc.parada
        if stop.destination:
            valor_bruto_dia += stop.destination.delivery_value or Decimal('0.00')
        elif stop.stop_type == 'DEVOLUCAO':
            dest = stop.service_order.destinations.first()
            if dest:
                valor_bruto_dia += dest.delivery_value or Decimal('0.00')

    if perfil.category == 'TELE':
        percentagem = Decimal(str(perfil.delivery_percentage or '100.00'))
        total_valor_dia = valor_bruto_dia * (percentagem / Decimal('100.00'))
    elif perfil.category == 'DIARIA':
        if entregas_concluidas_hoje > 0:
            total_valor_dia = Decimal(str(perfil.daily_rate or '0.00'))
        else:
            total_valor_dia = Decimal('0.00')
    elif perfil.category == 'MENSAL':
        total_valor_dia = Decimal(str(perfil.monthly_rate or '0.00'))
    else:
        total_valor_dia = Decimal('0.00')

    historico = ServiceOrder.objects.filter(motoboy=perfil, status__in=['ENTREGUE', 'CANCELADO']).order_by('-created_at')[:10]

    last_seen = cache.get(f'seen_{request.user.id}')
    is_absent = getattr(perfil, 'is_absent', False)
    is_online = perfil.is_available and bool(last_seen) and not is_absent
    presence_status = 'online' if is_online else ('ausente' if is_absent else 'offline')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        orders_json = []
        for data in ativas_data:
            os_obj = data['os']
            stops_json = []
            for stop in data['stops']:
                # Mapeamento do Endereço
                if stop.stop_type == 'COLETA':
                    name = os_obj.origin_name
                    address = f"{os_obj.origin_street or ''}, {os_obj.origin_number or ''} - {os_obj.origin_district or ''}".strip(' ,-')
                    comp = os_obj.origin_complement or ''
                    ref = os_obj.origin_reference or ''
                    contact = os_obj.origin_phone
                elif stop.stop_type == 'ENTREGA':
                    dest = stop.destination
                    name = dest.destination_name if dest else 'Destino Indefinido'
                    address = f"{dest.destination_street or ''}, {dest.destination_number or ''} - {dest.destination_district or ''}".strip(' ,-') if dest else ''
                    comp = dest.destination_complement or '' if dest else ''
                    ref = dest.destination_reference or '' if dest else 'Sem referência'
                    contact = dest.destination_phone if dest else '--'
                elif stop.stop_type == 'TRANSFERENCIA':
                    name = "Ponto de Encontro"
                    address = stop.custom_address or ''
                    comp = stop.custom_complement or ''
                    ref = "Sem referência"
                    contact = "--"
                else: # DEVOLUCAO
                    name = "Local de Devolução"
                    address = stop.custom_address or ''
                    comp = stop.custom_complement or ''
                    ref = "Sem referência"
                    contact = "--"

                # Mapeamento de Regras de Bloqueio 
                is_waiting_rescue = False
                if stop.failure_reason and '[AGUARDANDO SOCORRO]' in stop.failure_reason and not stop.is_completed:
                    is_waiting_rescue = True
                elif stop.custom_address and 'AGUARDE' in stop.custom_address and not stop.is_completed:
                    is_waiting_rescue = True
                    
                is_frozen = False
                if stop.failure_reason and stop.bloqueia_proxima and not stop.is_completed and '[AGUARDANDO SOCORRO]' not in stop.failure_reason:
                    is_frozen = True

                # Mapeamento dos Itens do Roteiro
                items_json = []
                if stop.stop_type == 'ENTREGA' and stop.destination:
                    for dist in stop.destination.distributed_items.all():
                        items_json.append({'desc': dist.item.description, 'qty': dist.quantity_allocated, 'type': dist.item.item_type or 'Item'})
                elif stop.stop_type == 'COLETA':
                    for item in os_obj.items.all():
                        items_json.append({'desc': item.description, 'qty': item.total_quantity, 'type': item.item_type or 'Item'})
                else:
                    for dest in os_obj.destinations.all():
                        if not dest.is_delivered:
                            for dist in dest.distributed_items.all():
                                items_json.append({'desc': f"{dist.item.description} (Retorno)", 'qty': dist.quantity_allocated, 'type': dist.item.item_type or 'Pacote'})
                    if data['has_children']:
                        for child in os_obj.child_orders.all():
                            for dest in child.destinations.all():
                                if not dest.is_delivered:
                                    for dist in dest.distributed_items.all():
                                        items_json.append({'desc': f"{dist.item.description} (Retorno)", 'qty': dist.quantity_allocated, 'type': dist.item.item_type or 'Pacote'})

                stops_json.append({
                    'id': str(stop.id),
                    'type': stop.stop_type,
                    'sequence': stop.sequence,
                    'is_completed': stop.is_completed,
                    'is_failed': stop.is_failed,
                    'bloqueia_proxima': stop.bloqueia_proxima,
                    'is_waiting_rescue': is_waiting_rescue,
                    'is_frozen': is_frozen,
                    'name': name,
                    'address': address,
                    'complement': comp,
                    'reference': ref,
                    'contact': contact,
                    'os_origem': stop.service_order.os_number,
                    'root_os_number': stop.service_order.parent_os.os_number if stop.service_order.parent_os else stop.service_order.os_number,
                    'items_details': items_json
                })
                
            orders_json.append({
                'id': str(os_obj.id),
                'os_number': os_obj.os_number,
                'priority': os_obj.priority,
                'priorityDisplay': os_obj.get_priority_display(),
                'status': os_obj.status,
                'has_children': data['has_children'],
                'child_numbers': ", ".join(data['child_numbers']),
                'stops': stops_json
            })
            
        return JsonResponse({
            'ativas_count': len(ativas_data),
            'entregas_concluidas': entregas_concluidas_hoje,
            'total_valor_dia': float(total_valor_dia),
            'presence_status': presence_status,
            'motoboy_is_available': perfil.is_available,
            'orders': orders_json
        })

    context = {
        'ativas_data': ativas_data,
        'historico': historico,
        'entregas_concluidas': entregas_concluidas_hoje,
        'total_valor_dia': total_valor_dia,
        'presence_status': presence_status,
        'is_online': is_online,
        'is_absent': is_absent,
    }
    return render(request, 'orders/motoboy_tasks.html', context)


@login_required
def motoboy_profile_view(request):
    if request.user.type != 'MOTOBOY':
        return redirect('root')

    perfil = getattr(request.user, 'motoboy_profile', None)

    cnh_invalida = not perfil.cnh_number or 'Pendente' in perfil.cnh_number
    placa_invalida = not perfil.vehicle_plate or 'Pendente' in perfil.vehicle_plate
    is_first_access = cnh_invalida or placa_invalida

    if request.method == 'POST':
        cnh_raw = (request.POST.get('cnh_number') or '').strip()
        placa_raw = (request.POST.get('vehicle_plate') or '').strip()
        if cnh_raw and not cnh_raw.startswith('Pendente'):
            ok, err = validate_cnh(cnh_raw)
            if not ok:
                messages.error(request, f'CNH: {err}')
                _ctx = _motoboy_profile_context(request, perfil, is_first_access)
                return render(request, 'orders/motoboy_profile.html', _ctx)
            perfil.cnh_number = clean_cnh(cnh_raw) or cnh_raw
        else:
            perfil.cnh_number = cnh_raw or perfil.cnh_number
        if placa_raw and not placa_raw.upper().startswith('PENDENTE'):
            ok, err = validate_plate(placa_raw)
            if not ok:
                messages.error(request, f'Placa: {err}')
                _ctx = _motoboy_profile_context(request, perfil, is_first_access)
                return render(request, 'orders/motoboy_profile.html', _ctx)
            perfil.vehicle_plate = clean_plate(placa_raw) or placa_raw.upper()[:7]
        else:
            perfil.vehicle_plate = placa_raw or perfil.vehicle_plate
        perfil.category = request.POST.get('category', perfil.category)

        request.user.first_name = request.POST.get('first_name', request.user.first_name)
        request.user.email = request.POST.get('email', request.user.email)
        request.user.phone = request.POST.get('phone', request.user.phone)
        request.user.save()

        cnh_agora_valida = perfil.cnh_number and 'Pendente' not in perfil.cnh_number
        placa_agora_valida = perfil.vehicle_plate and 'Pendente' not in perfil.vehicle_plate

        if cnh_agora_valida and placa_agora_valida:
            perfil.is_available = True

        perfil.save()
        messages.success(request, "Perfil atualizado com sucesso!")
        return redirect('motoboy_tasks')

    context = _motoboy_profile_context(request, perfil, is_first_access)
    return render(request, 'orders/motoboy_profile.html', context)


def _motoboy_profile_context(request, perfil, is_first_access):
    """Monta o contexto da página de perfil do motoboy (ganhos e datas)."""
    hoje_local = timezone.localtime(timezone.now()).date()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    start_date = parse_date(start_date_str) if start_date_str else hoje_local
    end_date = parse_date(end_date_str) if end_date_str else hoje_local
    
    # --- CORREÇÃO AQUI: ADICIONADO is_failed=False na base do filtro ---
    filter_concluidas = Q(motoboy=perfil, stop_type__in=['ENTREGA', 'DEVOLUCAO'], is_completed=True, is_failed=False)
    filter_oc = Q(motoboy=perfil, parada__stop_type__in=['ENTREGA', 'DEVOLUCAO']) & ~Q(causa='ACIDENTE')

    # Aplica os filtros de datas
    if start_date:
        filter_concluidas &= Q(completed_at__date__gte=start_date)
        filter_oc &= Q(criado_em__date__gte=start_date)
    if end_date:
        filter_concluidas &= Q(completed_at__date__lte=end_date)
        filter_oc &= Q(criado_em__date__lte=end_date)
        
    concluidas_qs = RouteStop.objects.filter(filter_concluidas).select_related('destination', 'service_order').prefetch_related('service_order__destinations')
    ocorrencias_qs = Occurrence.objects.filter(filter_oc).select_related('parada__destination', 'parada__service_order').prefetch_related('parada__service_order__destinations')
    
    qtd_entregas_periodo = 0
    valor_bruto_periodo = Decimal('0.00')
    dias_trabalhados_set = set()

    for stop in concluidas_qs:
        qtd_entregas_periodo += 1
        if stop.completed_at:
            dias_trabalhados_set.add(stop.completed_at.date())
            
        if stop.destination:
            valor_bruto_periodo += stop.destination.delivery_value or Decimal('0.00')
        elif stop.stop_type == 'DEVOLUCAO':
            dest = stop.service_order.destinations.first()
            if dest:
                valor_bruto_periodo += dest.delivery_value or Decimal('0.00')

    for oc in ocorrencias_qs:
        qtd_entregas_periodo += 1
        if oc.criado_em:
            dias_trabalhados_set.add(oc.criado_em.date())
            
        stop = oc.parada
        if stop.destination:
            valor_bruto_periodo += stop.destination.delivery_value or Decimal('0.00')
        elif stop.stop_type == 'DEVOLUCAO':
            dest = stop.service_order.destinations.first()
            if dest:
                valor_bruto_periodo += dest.delivery_value or Decimal('0.00')

    # Cálculo final com base na categoria
    if perfil.category == 'TELE':
        percentagem = Decimal(str(perfil.delivery_percentage or '100.00'))
        total_valor_periodo = valor_bruto_periodo * (percentagem / Decimal('100.00'))
    elif perfil.category == 'DIARIA':
        dias_trabalhados = len(dias_trabalhados_set)
        total_valor_periodo = Decimal(str(perfil.daily_rate or '0.00')) * dias_trabalhados
    elif perfil.category == 'MENSAL':
        total_valor_periodo = Decimal(str(perfil.monthly_rate or '0.00'))
    else:
        total_valor_periodo = Decimal('0.00')
        
    return {
        'perfil': perfil,
        'is_first_access': is_first_access,
        'start_date': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end_date': end_date.strftime('%Y-%m-%d') if end_date else '',
        'qtd_entregas_periodo': qtd_entregas_periodo,
        'total_valor_periodo': total_valor_periodo,
    }

@login_required
@require_POST
@transaction.atomic
def motoboy_update_status(request, stop_id):
    if request.user.type != 'MOTOBOY':
        return redirect('root')

    if not request.user.motoboy_profile.is_available:
        messages.error(request, "Ação bloqueada! O seu veículo está registado como avariado. Confirme o conserto primeiro.")
        return redirect('motoboy_tasks')

    current_stop = get_object_or_404(RouteStop.objects.select_for_update(), id=stop_id, motoboy__user=request.user)

    if not current_stop.is_completed:
        os = current_stop.service_order
        root_os = os.parent_os or os
        grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))

        if current_stop.stop_type in ['ENTREGA', 'DEVOLUCAO']:
            coleta_falhou = RouteStop.objects.filter(
                service_order=os,
                stop_type='COLETA',
                is_completed=False,
                is_failed=True
            ).exists()
            if coleta_falhou:
                messages.error(
                    request,
                    "Não é possível concluir esta entrega/devolução: a coleta desta OS teve problema. "
                    "Resolva a ocorrência na coleta no painel do despachante primeiro."
                )
                return redirect('motoboy_tasks')

        if current_stop.stop_type == 'ENTREGA' and current_stop.destination:
            dest = current_stop.destination
            receiver_name = request.POST.get('receiver_name')
            proof_photo = request.FILES.get('proof_photo')
            if receiver_name:
                dest.receiver_name = receiver_name
            if proof_photo:
                dest.proof_photo = proof_photo
            dest.is_delivered = True
            dest.delivered_at = timezone.now()
            dest.save()

            item_ids = ItemDistribution.objects.filter(destination=dest).values_list('item_id', flat=True)
            OSItem.objects.filter(id__in=item_ids).update(
                status=OSItem.ItemStatus.ENTREGUE,
                posse_atual=None
            )

        current_stop.is_completed = True
        current_stop.completed_at = timezone.now()
        current_stop.save()

        if current_stop.stop_type == 'TRANSFERENCIA':
            RouteStop.objects.filter(
                service_order__in=grouped_orders,
                stop_type='TRANSFERENCIA',
                is_completed=False
            ).exclude(motoboy=current_stop.motoboy).update(
                is_completed=True,
                status=RouteStop.StopStatus.CONCLUIDA,
                completed_at=timezone.now()
            )

            OSItem.objects.filter(
                order__in=grouped_orders,
                status=OSItem.ItemStatus.TRANSFERIDO
            ).update(
                status=OSItem.ItemStatus.COLETADO,
                posse_atual=current_stop.motoboy
            )
            messages.success(request, f"Carga assumida com sucesso!")

        if current_stop.stop_type == 'COLETA':
            grouped_orders.update(status='COLETADO')

            OSItem.objects.filter(order__in=grouped_orders).update(
                status=OSItem.ItemStatus.COLETADO,
                posse_atual=current_stop.motoboy
            )
            messages.success(request, f"Coleta confirmada! Os itens estão agora em sua posse.")

        elif current_stop.stop_type in ['ENTREGA', 'DEVOLUCAO']:
            paradas_restantes = RouteStop.objects.filter(
                service_order__in=grouped_orders,
                motoboy=current_stop.motoboy,
                is_completed=False
            ).count()

            if paradas_restantes == 0:
                total_geral_restantes = RouteStop.objects.filter(
                    service_order__in=grouped_orders, is_completed=False
                ).count()

                if total_geral_restantes == 0:
                    os.status = 'ENTREGUE'
                    os.save()
                messages.success(request, f"Todas as suas tarefas desta OS foram concluídas!")
            else:
                messages.success(request, f"Etapa confirmada! Partindo para o próximo destino.")

    return redirect('motoboy_tasks')


@login_required
def motoboy_heartbeat_view(request):
    """Recebe o sinal do aplicativo/tela do motoboy para mantê-lo online"""
    if request.user.type == 'MOTOBOY':
        cache.set(f'seen_{request.user.id}', True, timeout=300)
        return JsonResponse({'status': 'online'})
    return JsonResponse({'status': 'ignored'})


@login_required
@require_POST
def motoboy_set_presence_view(request):
    """Motoboy define presença: online (iniciar acesso) ou ausente"""
    if request.user.type != 'MOTOBOY':
        return JsonResponse({'status': 'error', 'message': 'Sem permissão.'}, status=403)
    try:
        perfil = request.user.motoboy_profile
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Perfil não encontrado.'}, status=400)
    data = request.POST
    if request.content_type and 'application/json' in request.content_type:
        data = json.loads(request.body) if request.body else {}
    status = (data.get('status') or '').strip().upper()
    if status == 'ONLINE':
        perfil.is_absent = False
        perfil.save(update_fields=['is_absent'])
        cache.set(f'seen_{request.user.id}', True, timeout=300)
        return JsonResponse({'status': 'ok', 'presence': 'online'})
    if status == 'AUSENTE':
        perfil.is_absent = True
        perfil.save(update_fields=['is_absent'])
        return JsonResponse({'status': 'ok', 'presence': 'ausente'})
    return JsonResponse({'status': 'error', 'message': 'Use status=online ou status=ausente.'}, status=400)


@login_required
@require_POST
def report_problem_view(request, stop_id):
    """Regista uma ocorrência oficial, salva evidências e decide o estado da rota"""
    if request.user.type != 'MOTOBOY':
        return redirect('root')

    current_stop = get_object_or_404(RouteStop, id=stop_id, motoboy__user=request.user)
    os_atual = current_stop.service_order
    motoboy_profile = request.user.motoboy_profile

    causa = request.POST.get('causa')
    observacao = request.POST.get('observacao', '')
    evidencia_foto = request.FILES.get('evidencia_foto')

    pode_seguir = request.POST.get('pode_seguir') == 'on'

    if not causa:
        messages.error(request, "A causa da ocorrência é obrigatória.")
        return redirect('motoboy_tasks')

    ocorrencia = Occurrence.objects.create(
        parada=current_stop,
        service_order=os_atual,
        motoboy=motoboy_profile,
        causa=causa,
        observacao=observacao,
        evidencia_foto=evidencia_foto,
        urgencia=Occurrence.Urgencia.ALTA if causa == 'ACIDENTE' else Occurrence.Urgencia.MEDIA
    )

    current_stop.status = RouteStop.StopStatus.COM_OCORRENCIA
    current_stop.is_failed = True
    current_stop.failure_reason = f"{ocorrencia.get_causa_display()}"
    current_stop.bloqueia_proxima = True if causa == 'ACIDENTE' else not pode_seguir
    if not current_stop.bloqueia_proxima:
        current_stop.sequence = 999

    current_stop.save()

    root_os = os_atual.parent_os or os_atual
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))

    if current_stop.stop_type == 'COLETA':
        RouteStop.objects.filter(
            service_order=os_atual,
            is_completed=False,
            stop_type__in=['ENTREGA', 'DEVOLUCAO']
        ).exclude(id=current_stop.id).update(
            is_failed=True,
            failure_reason="Coleta desta OS falhou. Resolva a ocorrência na coleta primeiro.",
            bloqueia_proxima=False
        )

    grouped_orders.update(status=ServiceOrder.Status.PROBLEM)

    nova_nota = f"\n[🚨 OCORRÊNCIA - {current_stop.get_stop_type_display()}] Motivo: {ocorrencia.get_causa_display()}."
    root_os.operational_notes += nova_nota
    root_os.save()

    if causa == 'ACIDENTE':
        motoboy_profile.is_available = False
        motoboy_profile.save()

        os_nao_coletadas = ServiceOrder.objects.filter(
            motoboy=motoboy_profile,
            status='ACEITO'
        ).exclude(
            Q(id=os_atual.id) | Q(parent_os=os_atual) | Q(id=os_atual.parent_os_id)
        )

        if os_nao_coletadas.exists():
            RouteStop.objects.filter(service_order__in=os_nao_coletadas, is_completed=False).update(motoboy=None, status='PENDENTE')
            os_nao_coletadas.update(motoboy=None, status='PENDENTE')

    messages.warning(request, "Ocorrência enviada! O despachante já foi notificado.")
    return redirect('motoboy_tasks')


@login_required
@require_POST
def motoboy_fix_vehicle_view(request):
    """Desbloqueia o motoboy após ele consertar o veículo"""
    if request.user.type != 'MOTOBOY':
        return JsonResponse({'error': 'Acesso negado'}, status=403)

    perfil = request.user.motoboy_profile
    perfil.is_available = True
    perfil.save()

    messages.success(request, "Veículo consertado! Você está online e disponível na base.")
    return redirect('motoboy_tasks')
