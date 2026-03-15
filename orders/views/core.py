"""Views centrais: redirecionamento pós-login, cancelar OS, detalhes da OS."""
import json
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Q

from orders.models import ServiceOrder, RouteStop, Occurrence


@login_required
def root_redirect(request):
    """Redireciona o usuário para o painel conforme o tipo (ADMIN, COMPANY, MOTOBOY, DISPATCHER)."""
    user = request.user
    if user.type == 'ADMIN' or user.is_superuser:
        return redirect('admin_dashboard')
    if user.type == 'COMPANY':
        return redirect('company_dashboard')
    if user.type == 'MOTOBOY':
        return redirect('motoboy_tasks')
    if user.type == 'DISPATCHER':
        return redirect('dispatch_dashboard')
    return redirect('login')


@login_required
@require_POST
def cancel_os_view(request, os_id):
    """Cancela uma OS (empresa dona ou despachante/admin)."""
    os = get_object_or_404(ServiceOrder, id=os_id)
    if request.user.type == 'COMPANY' and os.client != request.user:
        return JsonResponse({'status': 'error', 'message': 'Você não tem permissão para cancelar esta OS.'}, status=403)
    if os.status in ['COLETADO', 'ENTREGUE']:
        return JsonResponse({'status': 'error', 'message': 'Esta OS já está em rota ou foi entregue e não pode ser cancelada.'}, status=400)
    os.status = 'CANCELADO'
    os.motoboy = None
    os.save()
    from django.contrib import messages
    messages.success(request, f'A OS {os.os_number} foi cancelada com sucesso.')
    return JsonResponse({'status': 'success'})


@login_required
def dashboard(request):
    """Dashboard legado (lista de ordens por tipo de usuário)."""
    if request.user.type == 'ADMIN':
        orders = ServiceOrder.objects.all().order_by('-created_at')
    elif request.user.type == 'COMPANY':
        orders = ServiceOrder.objects.filter(client=request.user).order_by('-created_at')
    else:
        orders = ServiceOrder.objects.filter(motoboy__user=request.user).order_by('-created_at')
    return render(request, 'orders/dashboard.html', {'orders': orders})


@login_required
def os_details_view(request, os_id):
    """Exibe a visão completa de uma OS (itens, destinos, paradas, ocorrências)."""
    os_obj = get_object_or_404(ServiceOrder, id=os_id)
    if request.user.type not in ['ADMIN', 'DISPATCHER'] and not request.user.is_superuser:
        if request.user.type == 'COMPANY' and os_obj.client != request.user:
            return redirect('root')
        if request.user.type == 'MOTOBOY' and getattr(os_obj.motoboy, 'user', None) != request.user:
            return redirect('root')

    items = os_obj.items.all()
    destinations = os_obj.destinations.all()
    root_os = os_obj.parent_os or os_obj
    grouped_orders = ServiceOrder.objects.filter(Q(id=root_os.id) | Q(parent_os=root_os))
    stops = RouteStop.objects.filter(service_order__in=grouped_orders).order_by('sequence')
    ocorrencias = Occurrence.objects.filter(service_order__in=grouped_orders).order_by('-criado_em')

    context = {
        'os': os_obj,
        'root_os': root_os,
        'items': items,
        'destinations': destinations,
        'stops': stops,
        'ocorrencias': ocorrencias,
    }
    return render(request, 'orders/os_details.html', context)
