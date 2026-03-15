"""
Views do motoboy: tarefas, perfil, heartbeat, presença, reportar problema, conserto de veículo.
"""
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum, Subquery
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

# Paradas de ENTREGA que contam para valor: concluída OU já teve ocorrência (não-ACIDENTE). Valor não some após despachante resolver.
def _q_entregas_que_contam_valor():
    """Uma vez que o motoboy reportou (não-ACIDENTE), o valor permanece mesmo após REAGENDAR/RETORNAR."""
    paradas_com_ocorrencia_nao_acidente = Subquery(
        Occurrence.objects.exclude(causa=Occurrence.Causa.ACIDENTE).values_list('parada_id', flat=True).distinct()
    )
    return Q(stop_type__in=['ENTREGA', 'DEVOLUCAO']) & (
        Q(is_completed=True) | Q(id__in=paradas_com_ocorrencia_nao_acidente)
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

    # OS "em execução" = raiz da parada com menor sequência (evita confundir OS raiz com filha)
    if proxima_parada_global:
        root_da_proxima = proxima_parada_global.service_order.parent_os or proxima_parada_global.service_order
        os_em_execucao_id = root_da_proxima.id
    else:
        os_em_execucao_id = None

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

    # Regra: mais antigas primeiro — lista por data de criação (e pausadas agrupadas)
    ativas_data.sort(key=lambda x: (x['ta_pausada'], x['os'].created_at))
    hoje = timezone.now().date()
    q_entregas_valor = _q_entregas_que_contam_valor() & Q(motoboy=perfil)
    # Data: concluídas usam completed_at (valor conta no dia da entrega); só não concluídas usam data da ocorrência
    paradas_ocorrencia_hoje = Subquery(
        Occurrence.objects.exclude(causa=Occurrence.Causa.ACIDENTE).filter(criado_em__date=hoje).values_list('parada_id', flat=True)
    )
    q_hoje = q_entregas_valor & (
        (Q(is_completed=True) & Q(completed_at__date=hoje)) |
        (Q(is_completed=False) & Q(id__in=paradas_ocorrencia_hoje))
    )
    entregas_concluidas_hoje = RouteStop.objects.filter(q_hoje).distinct().count()

    ids_hoje = list(RouteStop.objects.filter(q_hoje).values_list('id', flat=True).distinct())
    valor_bruto_dia = RouteStop.objects.filter(id__in=ids_hoje).aggregate(
        total=Sum('destination__delivery_value')
    )['total'] or Decimal('0.00')

    if perfil.category == 'TELE':
        percentagem = Decimal(str(perfil.delivery_percentage or '100.00'))
        total_valor_dia = valor_bruto_dia * (percentagem / Decimal('100.00'))
    elif perfil.category == 'DIARIA':
        total_valor_dia = Decimal(str(perfil.daily_rate or '0.00'))
    elif perfil.category == 'MENSAL':
        total_valor_dia = Decimal(str(perfil.monthly_rate or '0.00'))
    else:
        total_valor_dia = Decimal('0.00')

    historico = ServiceOrder.objects.filter(motoboy=perfil, status__in=['ENTREGUE', 'CANCELADO']).order_by('-created_at')[:10]

    last_seen = cache.get(f'seen_{request.user.id}')
    is_absent = getattr(perfil, 'is_absent', False)
    is_online = perfil.is_available and bool(last_seen) and not is_absent
    presence_status = 'online' if is_online else ('ausente' if is_absent else 'offline')

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
    q_base = _q_entregas_que_contam_valor() & Q(motoboy=perfil)
    q_data = Q()
    # Concluídas: data = completed_at (valor no dia da entrega). Só não concluídas usam data da ocorrência.
    if start_date:
        paradas_ocorr_gte = Subquery(
            Occurrence.objects.exclude(causa=Occurrence.Causa.ACIDENTE).filter(criado_em__date__gte=start_date).values_list('parada_id', flat=True)
        )
        q_data &= (
            (Q(is_completed=True) & Q(completed_at__date__gte=start_date)) |
            (Q(is_completed=False) & Q(id__in=paradas_ocorr_gte))
        )
    if end_date:
        paradas_ocorr_lte = Subquery(
            Occurrence.objects.exclude(causa=Occurrence.Causa.ACIDENTE).filter(criado_em__date__lte=end_date).values_list('parada_id', flat=True)
        )
        q_data &= (
            (Q(is_completed=True) & Q(completed_at__date__lte=end_date)) |
            (Q(is_completed=False) & Q(id__in=paradas_ocorr_lte))
        )
    filter_q = q_base & q_data if q_data else q_base
    entregas_periodo = RouteStop.objects.filter(filter_q).distinct()
    qtd_entregas_periodo = entregas_periodo.count()
    ids_periodo = list(entregas_periodo.values_list('id', flat=True))
    valor_bruto_periodo = RouteStop.objects.filter(id__in=ids_periodo).aggregate(
        total=Sum('destination__delivery_value')
    )['total'] or Decimal('0.00')
    if perfil.category == 'TELE':
        percentagem = Decimal(str(perfil.delivery_percentage or '100.00'))
        total_valor_periodo = valor_bruto_periodo * (percentagem / Decimal('100.00'))
    elif perfil.category == 'DIARIA':
        dias_completos = set(RouteStop.objects.filter(filter_q, is_completed=True).values_list('completed_at__date', flat=True).distinct())
        dias_ocorrencias = set(
            Occurrence.objects.exclude(causa=Occurrence.Causa.ACIDENTE).filter(
                parada__motoboy=perfil, parada__stop_type__in=['ENTREGA', 'DEVOLUCAO'], parada__is_completed=False
            ).filter(criado_em__date__gte=start_date, criado_em__date__lte=end_date).values_list('criado_em__date', flat=True).distinct()
        )
        dias_trabalhados = len(dias_completos | dias_ocorrencias)
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
