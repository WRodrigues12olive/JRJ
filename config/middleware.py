# config/middleware.py (ou core/middleware.py)
from django.utils import timezone
from django.core.cache import cache
from logistics.models import MotoboyProfile

class ActiveUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.type == 'MOTOBOY':
            # Atualiza o cache "last_seen_ID" com o horário atual
            # Usamos cache (Redis/Memcached/LocMem) para não bater no banco a cada clique
            current_user = request.user
            now = timezone.now()
            
            # Opção A: Salvar no Cache (Mais rápido, menos banco)
            cache.set(f'seen_{current_user.id}', now, 300) # Expira em 300s (5 min)

            # Opção B: Salvar no Banco (Se quiser histórico real)
            # Isso exige um campo 'last_activity' no MotoboyProfile
            # MotoboyProfile.objects.filter(user=current_user).update(last_activity=now)

        response = self.get_response(request)
        return response