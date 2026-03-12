"""Views do painel da empresa: dashboard e criação de OS."""
import json
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction

from orders.models import (
    ServiceOrder,
    OSItem,
    OSDestination,
    ItemDistribution,
    RouteStop,
)


@login_required
def company_dashboard_view(request):
    """Dashboard da empresa: métricas e lista de OS ativas."""
    if request.user.type != 'COMPANY':
        return redirect('root')

    minhas_os = ServiceOrder.objects.filter(client=request.user).order_by('-created_at')
    metrics = {
        'pending': minhas_os.filter(status='PENDENTE').count(),
        'in_progress': minhas_os.filter(status__in=['ACEITO', 'COLETADO']).count(),
        'delivered': minhas_os.filter(status='ENTREGUE').count(),
        'canceled': minhas_os.filter(status='CANCELADO').count(),
        'total': minhas_os.count(),
    }
    ativas = minhas_os.exclude(status__in=['ENTREGUE', 'CANCELADO'])
    recentes = minhas_os[:5]
    context = {
        'metrics': metrics,
        'ativas': ativas,
        'recentes': recentes,
        'company_initials': request.user.first_name[:2].upper() if request.user.first_name else 'EM',
    }
    return render(request, 'orders/company_dashboard.html', context)


@login_required
def os_create_view(request):
    """Cria uma nova OS (POST JSON) ou exibe o formulário (GET)."""
    if request.user.type != 'COMPANY':
        return redirect('root')

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                os = ServiceOrder.objects.create(
                    client=request.user,
                    requester_name=data.get('requester_name', ''),
                    requester_phone=data.get('requester_phone', ''),
                    company_cnpj=data.get('company_cnpj', ''),
                    company_email=data.get('company_email', ''),
                    delivery_type=data.get('delivery_type', ''),
                    vehicle_type=data.get('vehicle_type', 'MOTO'),
                    priority=data.get('priority', 'NORMAL'),
                    payment_method=data.get('payment_method', 'FATURADO'),
                    operational_notes=data.get('general_notes', ''),
                    origin_name=data.get('origin_name', ''),
                    origin_street=data.get('origin_street', ''),
                    origin_number=data.get('origin_number', ''),
                    origin_district=data.get('origin_district', ''),
                    origin_city=data.get('origin_city', ''),
                    origin_state=data.get('origin_state', ''),
                    origin_zip_code=data.get('origin_zip_code', ''),
                    is_multiple_delivery=len(data.get('destinations', [])) > 1,
                )

                items_dict = {}
                for item_data in data.get('items', []):
                    peso_str = item_data.get('weight', '')
                    peso_val = max(0.0, float(peso_str)) if peso_str else None
                    novo_item = OSItem.objects.create(
                        order=os,
                        description=item_data['description'],
                        total_quantity=item_data['quantity'],
                        item_type=item_data.get('type', ''),
                        weight=peso_val,
                        dimensions=item_data.get('dimensions', ''),
                        item_notes=item_data.get('notes', ''),
                    )
                    items_dict[item_data['id']] = novo_item

                dest_dict = {}
                for dest_data in data.get('destinations', []):
                    val_recebido = str(dest_data.get('value', '0.00'))
                    val_final = max(Decimal('0.00'), Decimal(val_recebido)) if val_recebido else Decimal('0.00')
                    novo_dest = OSDestination.objects.create(
                        order=os,
                        destination_name=dest_data['name'],
                        destination_phone=dest_data['phone'],
                        destination_street=dest_data['street'],
                        destination_number=dest_data['number'],
                        destination_complement=dest_data.get('complement', ''),
                        destination_district=dest_data['district'],
                        destination_city=dest_data['city'],
                        destination_state=dest_data.get('state', ''),
                        destination_zip_code=dest_data.get('cep', ''),
                        destination_reference=dest_data.get('reference', ''),
                        delivery_value=val_final,
                    )
                    dest_dict[dest_data['id']] = novo_dest

                for dist_data in data.get('distributions', []):
                    ItemDistribution.objects.create(
                        item=items_dict[dist_data['item_id']],
                        destination=dest_dict[dist_data['dest_id']],
                        quantity_allocated=dist_data['quantity'],
                    )

                RouteStop.objects.create(
                    service_order=os,
                    stop_type='COLETA',
                    sequence=1,
                )
                seq = 2
                for dest_obj in dest_dict.values():
                    RouteStop.objects.create(
                        service_order=os,
                        stop_type='ENTREGA',
                        destination=dest_obj,
                        sequence=seq,
                    )
                    seq += 1

            return JsonResponse({'status': 'success', 'os_number': os.os_number})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return render(request, 'orders/os_create.html')
