# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from orders.views import ( 
    root_redirect, company_dashboard_view, 
    dispatch_dashboard_view, motoboy_tasks_view, 
    admin_dashboard_view, os_create_view, 
    motoboy_update_status, assign_motoboy_view, 
    report_problem_view, resolve_os_problem, os_details_view
)
from accounts.views import register_user_view, custom_logout
from orders import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/logout/', custom_logout, name='logout'),
    path('os/<int:os_id>/cancelar/', views.cancel_os_view, name='cancel_os'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', root_redirect, name='root'),
    
    # Painéis
    path('painel-admin/', admin_dashboard_view, name='admin_dashboard'),
    path('painel-empresa/', company_dashboard_view, name='company_dashboard'),
    path('painel-despacho/', dispatch_dashboard_view, name='dispatch_dashboard'),
    
    # OS
    path('nova-os/', os_create_view, name='os_create'),
    path('os/<int:os_id>/stops/', views.get_route_stops, name='get_route_stops'),
    path('os/mesclar/', views.merge_os_view, name='merge_os'),
    path('os/desfazer-mescla/', views.unmerge_os_view, name='unmerge_os'),
    
    # Motoboy
    path('minhas-entregas/', motoboy_tasks_view, name='motoboy_tasks'),
    path('minhas-entregas/atualizar/<int:stop_id>/', motoboy_update_status, name='motoboy_update_status'),
    path('minhas-entregas/problema/<int:stop_id>/', report_problem_view, name='report_problem'),
    path('motoboy/perfil/', views.motoboy_profile_view, name='motoboy_profile'),   
    path('motoboy/heartbeat/', views.motoboy_heartbeat_view, name='motoboy_heartbeat'),
    path('motoboy/presenca/', views.motoboy_set_presence_view, name='motoboy_set_presence'),
    path('motoboy/fix-vehicle/', views.motoboy_fix_vehicle_view, name='fix_vehicle'),
    
    # Despacho (Ações)
    path('painel-despacho/atribuir/<int:os_id>/', assign_motoboy_view, name='assign_motoboy'),
    path('painel-despacho/reordenar-paradas/', views.reorder_stops_view, name='reorder_stops'),
    path('os/<int:os_id>/detalhes/', os_details_view, name='os_details'),
    path('os/parada/<int:stop_id>/atualizar-valor/', views.update_stop_value_view, name='update_stop_value'),
    # Resolver ocorrência (fluxo oficial: por occurrence_id, com ações REAGENDAR/RETORNAR/VOLTAR_FILA/TRANSFERIR_MOTOBOY)
    path('orders/occurrence/<int:occurrence_id>/resolve/', views.resolve_occurrence_view, name='resolve_occurrence'),
    # Resolver por OS (usa a mesma lógica quando existe ocorrência; fallback legado quando não há)
    path('painel-despacho/resolver/<int:os_id>/', resolve_os_problem, name='resolve_os_problem'),
    path('painel-despacho/transferir/<int:os_id>/', views.transfer_route_view, name='transfer_route'),
    path('painel-despacho/devolver/<int:os_id>/', views.create_return_view, name='create_return'),
    
    # Outros
    path('painel-geral/cadastrar-usuario/', register_user_view, name='register_user'),
    # Admin
    path('admin-painel/gestao-os/', views.admin_os_management_view, name='admin_os_management'),
    path('admin-painel/motoboys/', views.admin_motoboy_list_view, name='admin_motoboy_list'),
    path('admin-painel/motoboys/<int:motoboy_id>/editar/', views.admin_motoboy_edit_view, name='admin_motoboy_edit'),
]

# Isto é crucial para que o Django consiga abrir a foto do acidente no modal do Despachante!
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)