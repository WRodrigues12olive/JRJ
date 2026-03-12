import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from faker import Faker

from orders.models import ServiceOrder, OSItem, OSDestination, ItemDistribution, RouteStop

CustomUser = get_user_model()

class Command(BaseCommand):
    help = 'Gera Ordens de Serviço fictícias mas realistas para testes.'

    def add_arguments(self, parser):
        parser.add_argument('quantidade', type=int, help='Número de OSs a gerar')

    def handle(self, *args, **kwargs):
        quantidade = kwargs['quantidade']
        
        # Inicia o Faker configurado para o Brasil
        fake = Faker('pt_BR')

        # 1. Garante que existe pelo menos um utilizador do tipo 'COMPANY' para ser o cliente
        empresa_user = CustomUser.objects.filter(type='COMPANY').first()
        if not empresa_user:
            empresa_user = CustomUser.objects.create_user(
                username=fake.user_name(),
                email=fake.company_email(),
                password='senha_teste',
                first_name=fake.company(),
                type='COMPANY'
            )
            self.stdout.write(self.style.SUCCESS(f"Criada empresa de teste: {empresa_user.first_name}"))

        descricoes_itens = ['Caixa de Documentos', 'Peça de Computador', 'Amostra de Sangue', 'Brinde Corporativo', 'Contrato Registrado', 'Equipamento de Rede']

        # 2. Gera as OSs
        with transaction.atomic():
            for i in range(quantidade):
                # Número aleatório de entregas para esta OS (1 a 3 entregas)
                num_entregas = random.randint(1, 3)
                
                # A. Cria a Capa da OS
                os = ServiceOrder.objects.create(
                    client=empresa_user,
                    requester_name=fake.name(),
                    requester_phone=fake.phone_number(),
                    priority=random.choice(['NORMAL', 'NORMAL', 'NORMAL', 'URGENTE', 'AGENDADA']), # Mais chances de ser Normal
                    vehicle_type=random.choice(['MOTO', 'MOTO', 'CARRO']),
                    status='PENDENTE',
                    
                    # Dados de Coleta
                    origin_name=fake.company(),
                    origin_responsible=fake.first_name(),
                    origin_phone=fake.phone_number(),
                    origin_street=fake.street_name(),
                    origin_number=fake.building_number(),
                    origin_district=fake.bairro(),
                    origin_city=fake.city(),
                    origin_state=fake.estado_sigla(),
                    origin_zip_code=fake.postcode(),
                    is_multiple_delivery=(num_entregas > 1)
                )

                # B. Cria a Paragem de Rota (RouteStop) para a Coleta
                RouteStop.objects.create(
                    service_order=os,
                    stop_type='COLETA',
                    sequence=1
                )

                # C. Gera os Destinos e Itens
                sequencia_paragem = 2
                for j in range(num_entregas):
                    # Cria o Item
                    item = OSItem.objects.create(
                        order=os,
                        description=random.choice(descricoes_itens),
                        total_quantity=random.randint(1, 5),
                        item_type='Pacote',
                        weight=round(random.uniform(0.5, 5.0), 2)
                    )

                    # Cria o Destino (com valor de entrega aleatório para testes)
                    valor_entrega = Decimal(str(round(random.uniform(5.00, 150.00), 2)))
                    dest = OSDestination.objects.create(
                        order=os,
                        destination_name=fake.name(),
                        destination_phone=fake.phone_number(),
                        destination_street=fake.street_name(),
                        destination_number=fake.building_number(),
                        destination_district=fake.bairro(),
                        destination_city=fake.city(),
                        destination_state=fake.estado_sigla(),
                        destination_zip_code=fake.postcode(),
                        destination_complement=random.choice(['', 'Sala 2', 'Apt 101', 'Casa B', 'Fundos']),
                        delivery_value=valor_entrega
                    )

                    # Vincula o Item ao Destino
                    ItemDistribution.objects.create(
                        item=item,
                        destination=dest,
                        quantity_allocated=item.total_quantity
                    )

                    # Cria a Paragem de Rota (RouteStop) para esta Entrega
                    RouteStop.objects.create(
                        service_order=os,
                        stop_type='ENTREGA',
                        destination=dest,
                        sequence=sequencia_paragem
                    )
                    sequencia_paragem += 1

                self.stdout.write(f"OS gerada: {os.os_number} ({num_entregas} entregas)")

        self.stdout.write(self.style.SUCCESS(f'\n{quantidade} Ordens de Serviço geradas com sucesso!'))