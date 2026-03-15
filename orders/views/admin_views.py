"""Views do painel admin: dashboard, gestão de OS, listagem e edição de motoboys."""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum, Subquery
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages

from accounts.models import CustomUser
from logistics.models import MotoboyProfile
from logistics.validators import validate_cnh, validate_plate, clean_cnh, clean_plate
from orders.models import ServiceOrder, RouteStop, Occurrence


@login_required
def admin_dashboard_view(request):
    """Dashboard do administrador: KPIs, visão global, alertas, ranking motoboys e empresas."""
    if not (request.user.type == 'ADMIN' or request.user.is_superuser):
        return redirect('root')

    kpis = {
        'pendentes': ServiceOrder.objects.filter(status='PENDENTE').count(),
        'em_andamento': ServiceOrder.objects.filter(status__in=['ACEITO', 'COLETADO']).count(),
        'entregues': ServiceOrder.objects.filter(status='ENTREGUE').count(),
        'ocorrencias': ServiceOrder.objects.filter(status__in=['OCORRENCIA', 'PROBLEM']).count(),
        'canceladas': ServiceOrder.objects.filter(status='CANCELADO').count(),
    }

    global_orders = ServiceOrder.objects.select_related('client', 'motoboy').order_by('-created_at')
    paginator = Paginator(global_orders, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    alertas = Occurrence.objects.filter(resolvida=False).select_related('service_order', 'motoboy').order_by('-criado_em')[:15]

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    # Entregas que contam: concluídas OU já tiveram ocorrência (não-ACIDENTE). Valor não some após despachante resolver.
    paradas_com_ocorrencia_nao_acidente = Subquery(
        Occurrence.objects.exclude(causa='ACIDENTE').values_list('parada_id', flat=True).distinct()
    )
    q_valor = Q(stop_type__in=['ENTREGA', 'DEVOLUCAO']) & (
        Q(is_completed=True) | Q(id__in=paradas_com_ocorrencia_nao_acidente)
    )
    if start_date or end_date:
        sd = parse_date(start_date) if start_date else None
        ed = parse_date(end_date) if end_date else None
        q_data = Q()
        # Concluídas: data = completed_at. Só não concluídas usam data da ocorrência.
        if sd:
            q_data &= (
                (Q(is_completed=True) & Q(completed_at__date__gte=sd)) |
                (Q(is_completed=False) & Q(id__in=paradas_com_ocorrencia_nao_acidente) & Q(ocorrencias__criado_em__date__gte=sd))
            )
        if ed:
            q_data &= (
                (Q(is_completed=True) & Q(completed_at__date__lte=ed)) |
                (Q(is_completed=False) & Q(id__in=paradas_com_ocorrencia_nao_acidente) & Q(ocorrencias__criado_em__date__lte=ed))
            )
        stops_ranking = RouteStop.objects.filter(q_valor, q_data).distinct().select_related('motoboy', 'destination')
        from collections import defaultdict
        by_mb = defaultdict(lambda: {'total_entregas': 0, 'valor_gerado': Decimal('0.00')})
        for s in stops_ranking:
            if s.motoboy_id:
                by_mb[s.motoboy_id]['total_entregas'] += 1
                by_mb[s.motoboy_id]['valor_gerado'] += (s.destination.delivery_value or Decimal('0.00'))
        motoboys_ranking = list(MotoboyProfile.objects.filter(id__in=by_mb).select_related('user'))
        for mb in motoboys_ranking:
            mb.total_entregas = by_mb[mb.id]['total_entregas']
            mb.valor_gerado = by_mb[mb.id]['valor_gerado']
        motoboys_ranking.sort(key=lambda m: (m.valor_gerado or Decimal('0.00'), m.total_entregas), reverse=True)
    else:
        # Sem filtro de data: concluídas + paradas que já tiveram ocorrência (não-ACIDENTE)
        filter_q = Q(route_stops__stop_type='ENTREGA') & (
            Q(route_stops__is_completed=True) | Q(route_stops__id__in=paradas_com_ocorrencia_nao_acidente)
        )
        motoboys_ranking = MotoboyProfile.objects.select_related('user').annotate(
            total_entregas=Count('route_stops', filter=filter_q, distinct=True),
            valor_gerado=Sum('route_stops__destination__delivery_value', filter=filter_q)
        ).order_by('-valor_gerado', '-total_entregas')

    for mb in motoboys_ranking:
        val_gerado = mb.valor_gerado or Decimal('0.00')
        percentagem = Decimal(str(mb.delivery_percentage or '100.00'))
        if mb.category == 'TELE':
            mb.calculo_ganho = val_gerado * (percentagem / Decimal('100.00'))
        elif mb.category == 'DIARIA':
            mb.calculo_ganho = Decimal(str(mb.daily_rate or '0.00'))
        elif mb.category == 'MENSAL':
            mb.calculo_ganho = Decimal(str(mb.monthly_rate or '0.00'))
        else:
            mb.calculo_ganho = Decimal('0.00')

    companies = CustomUser.objects.filter(type='COMPANY').annotate(
        total_pedidos=Count('orders'),
        concluidas=Count('orders', filter=Q(orders__status='ENTREGUE')),
        canceladas=Count('orders', filter=Q(orders__status='CANCELADO'))
    ).order_by('-total_pedidos')

    hoje = timezone.now().date()
    weekly_data = []
    dias_semana = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}
    max_entregas = 0
    dados_dias = []
    q_entregas_valor = Q(stop_type__in=['ENTREGA', 'DEVOLUCAO']) & (
        Q(is_completed=True) | Q(id__in=paradas_com_ocorrencia_nao_acidente)
    )
    for i in range(6, -1, -1):
        data_alvo = hoje - timedelta(days=i)
        total_dia = RouteStop.objects.filter(
            q_entregas_valor,
            (Q(is_completed=True) & Q(completed_at__date=data_alvo)) |
            (Q(is_completed=False) & Q(id__in=paradas_com_ocorrencia_nao_acidente) & Q(ocorrencias__criado_em__date=data_alvo))
        ).distinct().count()
        if total_dia > max_entregas:
            max_entregas = total_dia
        dados_dias.append({'data': data_alvo, 'total': total_dia})
    for dado in dados_dias:
        altura = (dado['total'] / max_entregas * 100) if max_entregas > 0 else 0
        if altura == 0:
            altura = 2
        weekly_data.append({
            'day': dias_semana[dado['data'].weekday()],
            'count': dado['total'],
            'height': altura
        })

    context = {
        'kpis': kpis,
        'page_obj': page_obj,
        'alertas': alertas,
        'motoboys': motoboys_ranking,
        'companies': companies,
        'start_date': start_date,
        'end_date': end_date,
        'weekly_data': weekly_data,
    }
    return render(request, 'orders/admin_dashboard.html', context)


@login_required
def admin_os_management_view(request):
    """Página de gestão de OS (filtros e listagem)."""
    if not (request.user.type == 'ADMIN' or request.user.is_superuser):
        return redirect('root')

    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    orders = ServiceOrder.objects.select_related('client', 'motoboy').all().order_by('-created_at')
    if query:
        orders = orders.filter(
            Q(os_number__icontains=query) | Q(client__first_name__icontains=query) | Q(client__username__icontains=query)
        )
    if status_filter:
        orders = orders.filter(status=status_filter)
    paginator = Paginator(orders, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'orders/admin_os_management.html', {
        'page_obj': page_obj,
        'q': query,
        'status_filter': status_filter,
    })


@login_required
def admin_motoboy_list_view(request):
    """Listagem de motoboys."""
    if not (request.user.type == 'ADMIN' or request.user.is_superuser):
        return redirect('root')
    motoboys = MotoboyProfile.objects.select_related('user').all().order_by('user__first_name')
    return render(request, 'orders/admin_motoboy_list.html', {'motoboys': motoboys})


@login_required
def admin_motoboy_edit_view(request, motoboy_id):
    """Edição do perfil do motoboy (dados, CNH, placa, financeiro)."""
    if not (request.user.type == 'ADMIN' or request.user.is_superuser):
        return redirect('root')

    motoboy = get_object_or_404(MotoboyProfile, id=motoboy_id)
    user_obj = motoboy.user

    if request.method == 'POST':
        user_obj.first_name = request.POST.get('first_name', user_obj.first_name)
        user_obj.email = request.POST.get('email', user_obj.email)
        user_obj.phone = request.POST.get('phone', user_obj.phone)
        user_obj.is_active = request.POST.get('is_active') == 'on'
        new_password = request.POST.get('new_password')
        if new_password and new_password.strip() != "":
            user_obj.set_password(new_password)
        user_obj.save()

        cnh_raw = (request.POST.get('cnh_number') or '').strip()
        placa_raw = (request.POST.get('vehicle_plate') or '').strip()
        if cnh_raw and not cnh_raw.startswith('Pendente'):
            ok, err = validate_cnh(cnh_raw)
            if not ok:
                messages.error(request, f'CNH: {err}')
                return render(request, 'orders/admin_motoboy_edit.html', {'motoboy': motoboy})
            motoboy.cnh_number = clean_cnh(cnh_raw) or cnh_raw
        elif cnh_raw:
            motoboy.cnh_number = cnh_raw
        else:
            motoboy.cnh_number = request.POST.get('cnh_number', motoboy.cnh_number)
        if placa_raw and not placa_raw.upper().startswith('PENDENTE'):
            ok, err = validate_plate(placa_raw)
            if not ok:
                messages.error(request, f'Placa: {err}')
                return render(request, 'orders/admin_motoboy_edit.html', {'motoboy': motoboy})
            motoboy.vehicle_plate = clean_plate(placa_raw) or placa_raw.upper()[:7]
        elif placa_raw:
            motoboy.vehicle_plate = placa_raw
        else:
            motoboy.vehicle_plate = request.POST.get('vehicle_plate', motoboy.vehicle_plate)
        motoboy.category = request.POST.get('category', motoboy.category)

        perc_req = request.POST.get('delivery_percentage')
        if perc_req:
            motoboy.delivery_percentage = max(0.0, min(100.0, float(perc_req)))
        daily_req = request.POST.get('daily_rate')
        if daily_req:
            motoboy.daily_rate = max(0.0, float(daily_req))
        monthly_req = request.POST.get('monthly_rate')
        if monthly_req:
            motoboy.monthly_rate = max(0.0, float(monthly_req))
        motoboy.save()
        messages.success(request, f"Perfil de {user_obj.first_name} atualizado com sucesso!")
        return redirect('admin_motoboy_list')

    return render(request, 'orders/admin_motoboy_edit.html', {'motoboy': motoboy})
