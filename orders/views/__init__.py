"""
Pacote de views do app orders.
Re-exporta todas as views para manter compatibilidade com:
  from orders.views import ...
  from orders import views; views.xxx
"""
from .core import (
    root_redirect,
    cancel_os_view,
    dashboard,
    os_details_view,
)
from .company import (
    company_dashboard_view,
    os_create_view,
)
from .dispatch import (
    resolve_occurrence_view,
    resolve_os_problem,
    dispatch_dashboard_view,
    get_route_stops,
    merge_os_view,
    unmerge_os_view,
    assign_motoboy_view,
    reorder_stops_view,
    transfer_route_view,
    create_return_view,
    update_stop_value_view,
)
from .motoboy import (
    motoboy_tasks_view,
    motoboy_profile_view,
    motoboy_update_status,
    motoboy_heartbeat_view,
    motoboy_set_presence_view,
    report_problem_view,
    motoboy_fix_vehicle_view,
)
from .admin_views import (
    admin_dashboard_view,
    admin_os_management_view,
    admin_motoboy_list_view,
    admin_motoboy_edit_view,
)

__all__ = [
    'root_redirect',
    'cancel_os_view',
    'dashboard',
    'os_details_view',
    'company_dashboard_view',
    'os_create_view',
    'resolve_occurrence_view',
    'resolve_os_problem',
    'dispatch_dashboard_view',
    'get_route_stops',
    'merge_os_view',
    'unmerge_os_view',
    'assign_motoboy_view',
    'reorder_stops_view',
    'transfer_route_view',
    'create_return_view',
    'update_stop_value_view',
    'motoboy_tasks_view',
    'motoboy_profile_view',
    'motoboy_update_status',
    'motoboy_heartbeat_view',
    'motoboy_set_presence_view',
    'report_problem_view',
    'motoboy_fix_vehicle_view',
    'admin_dashboard_view',
    'admin_os_management_view',
    'admin_motoboy_list_view',
    'admin_motoboy_edit_view',
]
