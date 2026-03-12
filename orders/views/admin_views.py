"""Views do painel admin: dashboard, gestão de OS, listagem e edição de motoboys."""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
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
    
    hoje = timezone.now().date()

    start_date_resumo_str = request.GET.get('start_date_resumo')
    end_date_resumo_str = request.GET.get('end_date_resumo')

    if start_date_resumo_str:
        start_date_resumo = parse_date(start_date_resumo_str)
    else:
        start_date_resumo = hoje.replace(day=1) 

    if end_date_resumo_str:
        end_date_resumo = parse_date(end_date_resumo_str)
    else:
        end_date_resumo = hoje

    kpis = {
        'pendentes': ServiceOrder.objects.filter(
            status='PENDENTE',
            created_at__date__gte=start_date_resumo,
            created_at__date__lte=end_date_resumo
        ).count(),
        'em_andamento': RouteStop.objects.filter(
            stop_type='ENTREGA', 
            is_completed=False, 
            service_order__status__in=['ACEITO', 'COLETADO'],
            service_order__created_at__date__gte=start_date_resumo,
            service_order__created_at__date__lte=end_date_resumo
        ).count(),
        'entregues': RouteStop.objects.filter(
            stop_type='ENTREGA',
            is_completed=True,
            is_failed=False,
            completed_at__date__gte=start_date_resumo,
            completed_at__date__lte=end_date_resumo
        ).count(),
        'ocorrencias': ServiceOrder.objects.filter(
            status__in=['OCORRENCIA', 'PROBLEM'],
            created_at__date__gte=start_date_resumo,
            created_at__date__lte=end_date_resumo
        ).count(),
        'canceladas': ServiceOrder.objects.filter(
            status='CANCELADO',
            created_at__date__gte=start_date_resumo,
            created_at__date__lte=end_date_resumo
        ).count(),
    }

    global_orders = ServiceOrder.objects.select_related('client', 'motoboy').order_by('-created_at')
    paginator = Paginator(global_orders, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    alertas = Occurrence.objects.filter(resolvida=False).select_related('service_order', 'motoboy').order_by('-criado_em')[:15]

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    start_date_obj = parse_date(start_date) if start_date else None
    end_date_obj = parse_date(end_date) if end_date else None

    # 1. Filtros idênticos aos do Extrato do Motoboy
    filter_concluidas = Q(stop_type__in=['ENTREGA', 'DEVOLUCAO'], is_completed=True, is_failed=False)
    filter_oc = Q(parada__stop_type__in=['ENTREGA', 'DEVOLUCAO']) & ~Q(causa='ACIDENTE')

    if start_date_obj:
        filter_concluidas &= Q(completed_at__date__gte=start_date_obj)
        filter_oc &= Q(criado_em__date__gte=start_date_obj)
    if end_date_obj:
        filter_concluidas &= Q(completed_at__date__lte=end_date_obj)
        filter_oc &= Q(criado_em__date__lte=end_date_obj)

    concluidas_qs = RouteStop.objects.filter(filter_concluidas).select_related('motoboy', 'destination', 'service_order').prefetch_related('service_order__destinations')
    ocorrencias_qs = Occurrence.objects.filter(filter_oc).select_related('motoboy', 'parada__destination', 'parada__service_order').prefetch_related('parada__service_order__destinations')

    motoboys = MotoboyProfile.objects.select_related('user').all()
    dados_por_motoboy = {}
    
    for mb in motoboys:
        dados_por_motoboy[mb.id] = {
            'perfil': mb,
            'total_entregas': 0,
            'valor_gerado': Decimal('0.00'),
            'dias_trabalhados_set': set()
        }

    # 2. Soma as Entregas e Devoluções de Sucesso
    for stop in concluidas_qs:
        if stop.motoboy_id not in dados_por_motoboy: continue
        dados = dados_por_motoboy[stop.motoboy_id]
        dados['total_entregas'] += 1
        if stop.completed_at: dados['dias_trabalhados_set'].add(stop.completed_at.date())
        
        if stop.destination:
            dados['valor_gerado'] += stop.destination.delivery_value or Decimal('0.00')
        elif stop.stop_type == 'DEVOLUCAO':
            dest = stop.service_order.destinations.first()
            if dest: dados['valor_gerado'] += dest.delivery_value or Decimal('0.00')

    # 3. Soma as Tentativas Válidas (Ocorrências de clientes ausentes, etc)
    for oc in ocorrencias_qs:
        if oc.motoboy_id not in dados_por_motoboy: continue
        dados = dados_por_motoboy[oc.motoboy_id]
        dados['total_entregas'] += 1
        if oc.criado_em: dados['dias_trabalhados_set'].add(oc.criado_em.date())
            
        stop = oc.parada
        if stop.destination:
            dados['valor_gerado'] += stop.destination.delivery_value or Decimal('0.00')
        elif stop.stop_type == 'DEVOLUCAO':
            dest = stop.service_order.destinations.first()
            if dest: dados['valor_gerado'] += dest.delivery_value or Decimal('0.00')

    # 4. Aplica as regras de negócio de pagamento (Tele, Diária ou Mensal)
    motoboys_ranking = []
    for mb_id, dados in dados_por_motoboy.items():
        mb = dados['perfil']
        mb.total_entregas = dados['total_entregas']
        mb.valor_gerado = dados['valor_gerado']
        
        if mb.category == 'TELE':
            percentagem = Decimal(str(mb.delivery_percentage or '100.00'))
            mb.calculo_ganho = mb.valor_gerado * (percentagem / Decimal('100.00'))
        elif mb.category == 'DIARIA':
            dias_trabalhados = len(dados['dias_trabalhados_set'])
            mb.calculo_ganho = Decimal(str(mb.daily_rate or '0.00')) * dias_trabalhados
        elif mb.category == 'MENSAL':
            mb.calculo_ganho = Decimal(str(mb.monthly_rate or '0.00'))
        else:
            mb.calculo_ganho = Decimal('0.00')
            
        # CORREÇÃO: Adiciona TODOS os motoboys ao ranking, mesmo os que têm 0 entregas no período.
        # Assim o painel mostra sempre a equipa completa!
        motoboys_ranking.append(mb)
        
    # Ordena os que mais geraram valor e entregas para o topo
    motoboys_ranking.sort(key=lambda x: (x.valor_gerado, x.total_entregas), reverse=True)

    companies = CustomUser.objects.filter(type='COMPANY').annotate(
        total_pedidos=Count('orders'),
        concluidas=Count('orders', filter=Q(orders__status='ENTREGUE')),
        canceladas=Count('orders', filter=Q(orders__status='CANCELADO'))
    ).order_by('-total_pedidos')

    hoje = timezone.now().date()
    start_date_chart_str = request.GET.get('start_date_chart')
    end_date_chart_str = request.GET.get('end_date_chart')

    end_date_chart = parse_date(end_date_chart_str) if end_date_chart_str else hoje
    start_date_chart = parse_date(start_date_chart_str) if start_date_chart_str else end_date_chart - timedelta(days=6)

    # Proteção: Garante que a data inicial não é maior que a final e limita a 31 dias
    delta_days = (end_date_chart - start_date_chart).days
    if delta_days < 0:
        start_date_chart, end_date_chart = end_date_chart, start_date_chart
        delta_days = (end_date_chart - start_date_chart).days
    
    if delta_days > 31: 
        start_date_chart = end_date_chart - timedelta(days=31)
        delta_days = 31

    weekly_data = []
    dias_semana = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}
    max_entregas = 0
    dados_dias = []
    
    # Busca os dias no intervalo selecionado
    for i in range(delta_days + 1):
        data_alvo = start_date_chart + timedelta(days=i)
        total_dia = RouteStop.objects.filter(
            stop_type='ENTREGA', is_completed=True, is_failed=False, completed_at__date=data_alvo
        ).count()
        if total_dia > max_entregas:
            max_entregas = total_dia
        dados_dias.append({'data': data_alvo, 'total': total_dia})
        
    for dado in dados_dias:
        altura = (dado['total'] / max_entregas * 100) if max_entregas > 0 else 0
        if altura == 0:
            altura = 2
        # Formata o texto para exibir "Seg 12/05"
        label_dia = f"{dias_semana[dado['data'].weekday()]} {dado['data'].strftime('%d/%m')}"
        weekly_data.append({
            'day': label_dia,
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
        'start_date_resumo': start_date_resumo.strftime('%Y-%m-%d') if start_date_resumo else '',
        'end_date_resumo': end_date_resumo.strftime('%Y-%m-%d') if end_date_resumo else '',
        'start_date_chart': start_date_chart.strftime('%Y-%m-%d'),
        'end_date_chart': end_date_chart.strftime('%Y-%m-%d'),
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
        if status_filter == 'EM_ROTA':
            orders = orders.filter(status__in=['ACEITO', 'COLETADO'])
        elif status_filter == 'COM_OCORRENCIA':
            orders = orders.filter(
                Q(status='OCORRENCIA') | Q(ocorrencias__resolvida=False)
            ).distinct()
        else:
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
