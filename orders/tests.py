"""
Testes do app orders: occurrence_actions, services e views críticas.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from orders.models import (
    ServiceOrder,
    RouteStop,
    OSItem,
    OSDestination,
    Occurrence,
    DispatcherDecision,
)
from orders.views.occurrence_actions import apply_reagendar, apply_voltar_fila
from logistics.models import MotoboyProfile

User = get_user_model()


class OccurrenceActionsTest(TestCase):
    """Testes para apply_reagendar e apply_voltar_fila."""

    def setUp(self):
        self.user_dispatch = User.objects.create_user(
            username='despachante1',
            password='test123',
            type='DISPATCHER',
            first_name='Despachante'
        )
        self.user_company = User.objects.create_user(
            username='empresa1',
            password='test123',
            type='COMPANY',
            first_name='Empresa'
        )
        self.user_motoboy = User.objects.create_user(
            username='motoboy1',
            password='test123',
            type='MOTOBOY',
            first_name='Motoboy'
        )
        self.motoboy_profile = MotoboyProfile.objects.create(
            user=self.user_motoboy,
            cnh_number='12345678900',
            vehicle_plate='ABC1D23',
            category='TELE',
            is_available=True,
        )
        self.os = ServiceOrder.objects.create(
            client=self.user_company,
            requester_name='Solicitante',
            requester_phone='11999999999',
            origin_name='Origem',
            origin_street='Rua A',
            origin_number='1',
            origin_district='Centro',
            origin_city='São Paulo',
            origin_zip_code='01000000',
            status='ACEITO',
            motoboy=self.motoboy_profile,
        )
        self.dest = OSDestination.objects.create(
            order=self.os,
            destination_name='Destino',
            destination_phone='11888888888',
            destination_street='Rua B',
            destination_number='2',
            destination_district='Centro',
            destination_city='São Paulo',
            destination_zip_code='01000000',
        )
        self.stop_coleta = RouteStop.objects.create(
            service_order=self.os,
            motoboy=self.motoboy_profile,
            stop_type='COLETA',
            sequence=1,
            is_completed=True,
        )
        self.stop_entrega = RouteStop.objects.create(
            service_order=self.os,
            motoboy=self.motoboy_profile,
            destination=self.dest,
            stop_type='ENTREGA',
            sequence=2,
            is_completed=False,
            is_failed=True,
            failure_reason='Destinatário ausente',
        )
        self.occurrence = Occurrence.objects.create(
            parada=self.stop_entrega,
            service_order=self.os,
            motoboy=self.motoboy_profile,
            causa=Occurrence.Causa.AUSENTE,
            resolvida=False,
        )

    def test_apply_voltar_fila_desvincula_os_e_resolve_ocorrencia(self):
        """apply_voltar_fila deve colocar OS em PENDENTE, desvincular motoboy e marcar ocorrência resolvida."""
        apply_voltar_fila(self.occurrence, self.user_dispatch)
        self.os.refresh_from_db()
        self.occurrence.refresh_from_db()
        self.assertTrue(self.occurrence.resolvida)
        self.assertEqual(self.os.status, 'PENDENTE')
        self.assertIsNone(self.os.motoboy_id)
        self.assertEqual(
            DispatcherDecision.objects.filter(occurrence=self.occurrence, acao='VOLTAR_FILA').count(),
            1
        )

    def test_apply_reagendar_reativa_parada_e_resolve_ocorrencia(self):
        """apply_reagendar deve limpar falha da parada e marcar ocorrência resolvida."""
        apply_reagendar(self.occurrence, self.user_dispatch)
        self.occurrence.refresh_from_db()
        self.stop_entrega.refresh_from_db()
        self.assertTrue(self.occurrence.resolvida)
        self.assertFalse(self.stop_entrega.is_failed)
        self.assertEqual(self.stop_entrega.failure_reason, '')
        self.assertEqual(
            DispatcherDecision.objects.filter(
                occurrence=self.occurrence,
                acao=DispatcherDecision.Acao.REAGENDAR
            ).count(),
            1
        )


class RootRedirectTest(TestCase):
    """Testes para root_redirect por tipo de usuário."""

    def setUp(self):
        self.client = Client()

    def test_company_redirects_to_company_dashboard(self):
        User.objects.create_user(username='c1', password='test', type='COMPANY', first_name='E1')
        self.client.login(username='c1', password='test')
        response = self.client.get(reverse('root'))
        self.assertRedirects(response, reverse('company_dashboard'))

    def test_dispatcher_redirects_to_dispatch_dashboard(self):
        User.objects.create_user(username='d1', password='test', type='DISPATCHER', first_name='D1')
        self.client.login(username='d1', password='test')
        response = self.client.get(reverse('root'))
        self.assertRedirects(response, reverse('dispatch_dashboard'))

    def test_motoboy_redirects_to_motoboy_tasks(self):
        u = User.objects.create_user(username='m1', password='test', type='MOTOBOY', first_name='M1')
        MotoboyProfile.objects.create(user=u, cnh_number='x', vehicle_plate='y', category='TELE')
        self.client.login(username='m1', password='test')
        response = self.client.get(reverse('root'))
        self.assertRedirects(response, reverse('motoboy_tasks'))

    def test_admin_redirects_to_admin_dashboard(self):
        User.objects.create_user(username='a1', password='test', type='ADMIN', first_name='A1', is_staff=True)
        self.client.login(username='a1', password='test')
        response = self.client.get(reverse('root'))
        self.assertRedirects(response, reverse('admin_dashboard'))


class ResolveOccurrencePermissionTest(TestCase):
    """Teste de permissão: apenas despachante pode resolver ocorrência."""

    def setUp(self):
        self.client = Client()
        self.user_company = User.objects.create_user(
            username='empresa2', password='test', type='COMPANY', first_name='E2'
        )
        self.user_dispatch = User.objects.create_user(
            username='disp2', password='test', type='DISPATCHER', first_name='D2'
        )
        # Ocorrência mínima para ter um occurrence_id
        u_m = User.objects.create_user(username='motoboy2', password='test', type='MOTOBOY', first_name='M2')
        mb = MotoboyProfile.objects.create(user=u_m, cnh_number='x', vehicle_plate='y', category='TELE')
        os = ServiceOrder.objects.create(
            client=self.user_company,
            requester_name='S',
            requester_phone='1',
            origin_name='O',
            origin_street='R',
            origin_number='1',
            origin_district='C',
            origin_city='SP',
            origin_zip_code='01000000',
            status='ACEITO',
            motoboy=mb,
        )
        stop = RouteStop.objects.create(
            service_order=os, motoboy=mb, stop_type='COLETA', sequence=1, is_completed=False
        )
        self.occ = Occurrence.objects.create(
            parada=stop, service_order=os, motoboy=mb, causa=Occurrence.Causa.AUSENTE, resolvida=False
        )

    def test_resolve_occurrence_returns_403_for_company(self):
        self.client.login(username='empresa2', password='test')
        url = reverse('resolve_occurrence', args=[self.occ.id])
        response = self.client.post(
            url,
            data='{"acao": "VOLTAR_FILA"}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
