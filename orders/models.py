from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from logistics.models import MotoboyProfile
import uuid


class ServiceOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDENTE', 'Pendente'
        AGRUPADO = 'AGRUPADO', 'Agrupado'
        ACCEPTED = 'ACEITO', 'OS com o Motoboy'
        COLLECTED = 'COLETADO', 'Coletado / Em Trânsito'
        DELIVERED = 'ENTREGUE', 'Entregue'
        CANCELED = 'CANCELADO', 'Cancelado'
        PROBLEM = 'OCORRENCIA', 'Ocorrência / Problema'

    class Priority(models.TextChoices):
        NORMAL = 'NORMAL', 'Normal'
        URGENT = 'URGENTE', 'Urgente'
        SCHEDULED = 'AGENDADA', 'Agendada' 

    class PaymentMethod(models.TextChoices):
        INVOICED = 'FATURADO', 'Faturado/Empresa'
        RECEIVER = 'DESTINATARIO', 'Cobrar Destinatário'

    class VehicleType(models.TextChoices):
        MOTO = 'MOTO', 'Moto'
        CAR = 'CARRO', 'Carro'
        UTILITY = 'UTILITARIO', 'Utilitário'

    os_number = models.CharField(max_length=20, unique=True, editable=False, verbose_name="Número da OS")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL, verbose_name="Prioridade")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Status Atual")
    
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders', verbose_name="Empresa Solicitante")
    motoboy = models.ForeignKey(MotoboyProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries', verbose_name="Motoboy Responsável")

    requester_name = models.CharField(max_length=100, verbose_name="Nome do Solicitante")
    requester_phone = models.CharField(max_length=20, verbose_name="Telefone do Solicitante")
    company_cnpj = models.CharField(max_length=20, blank=True, null=True, verbose_name="CNPJ Solicitante")
    company_email = models.EmailField(blank=True, null=True, verbose_name="E-mail Solicitante")
    delivery_type = models.CharField(max_length=50, blank=True, null=True, verbose_name="Tipo de Entrega")
    origin_state = models.CharField(max_length=2, blank=True, null=True, verbose_name="UF (Coleta)")
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices, default=VehicleType.MOTO)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.INVOICED)
    internal_code = models.CharField(max_length=50, blank=True, verbose_name="Código Interno / Centro de Custo")
    is_exclusive_service = models.BooleanField(default=False, verbose_name="Serviço Exclusivo (+ Taxa)")
    requires_return = models.BooleanField(default=False, verbose_name="Adicionar Retorno")

    origin_name = models.CharField(max_length=100, verbose_name="Nome na Coleta")
    origin_responsible = models.CharField(max_length=100, verbose_name="Responsável Coleta")
    origin_phone = models.CharField(max_length=20, verbose_name="Telefone Coleta")
    origin_street = models.CharField(max_length=255, verbose_name="Rua (Coleta)")
    origin_number = models.CharField(max_length=20, verbose_name="Número (Coleta)")
    origin_complement = models.CharField(max_length=100, blank=True, verbose_name="Complemento (Coleta)")
    origin_district = models.CharField(max_length=100, verbose_name="Bairro (Coleta)")
    origin_city = models.CharField(max_length=100, verbose_name="Cidade (Coleta)")
    origin_zip_code = models.CharField(max_length=10, verbose_name="CEP (Coleta)")
    origin_reference = models.CharField(max_length=255, blank=True, verbose_name="Ponto de Referência (Coleta)")
    origin_notes = models.TextField(blank=True, verbose_name="Observações da Coleta") # Do Prompt Novo

    expected_pickup = models.DateTimeField(null=True, blank=True, verbose_name="Previsão de Coleta")
    expected_delivery = models.DateTimeField(null=True, blank=True, verbose_name="Previsão de Entrega (Geral)")
    time_window = models.CharField(max_length=100, blank=True, verbose_name="Janela de Horário")
    operational_notes = models.TextField(blank=True, verbose_name="Observações Gerais / Operacionais")

    collected_at = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora Coleta Real")
    geo_pickup_lat = models.CharField(max_length=50, blank=True, verbose_name="Geo Coleta (Lat)")
    geo_pickup_lng = models.CharField(max_length=50, blank=True, verbose_name="Geo Coleta (Lng)")
    is_multiple_delivery = models.BooleanField(default=False, editable=False) 
    parent_os = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_orders', help_text="Se esta OS foi mesclada dentro de outra, a 'Mãe' aparecerá aqui.")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.os_number:
            self.os_number = f"OS-{str(self.id).zfill(4)}"
            kwargs['force_insert'] = False
            super().save(update_fields=['os_number'])

    def __str__(self):
        return f"OS {self.os_number} - {self.status}"


class OSItem(models.Model):
    # Faltava esta classe!
    class ItemStatus(models.TextChoices):
        NAO_COLETADO = 'NAO_COLETADO', 'Não Coletado'
        COLETADO = 'COLETADO', 'Coletado (Em posse)'
        TRANSFERIDO = 'TRANSFERIDO', 'Transferido'
        ENTREGUE = 'ENTREGUE', 'Entregue'
        RETORNADO = 'RETORNADO', 'Retornado'
        EXTRAVIADO = 'EXTRAVIADO', 'Extraviado'

    order = models.ForeignKey(ServiceOrder, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=200, verbose_name="Descrição do Item")
    total_quantity = models.PositiveIntegerField(verbose_name="Quantidade Total")
    status = models.CharField(max_length=20, choices=ItemStatus.choices, default=ItemStatus.NAO_COLETADO)
    posse_atual = models.ForeignKey('logistics.MotoboyProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='itens_em_posse')
    item_type = models.CharField(max_length=50, blank=True, null=True, verbose_name="Tipo de Item")
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Peso (kg)")
    dimensions = models.CharField(max_length=50, blank=True, verbose_name="Dimensões (CxLxA)")
    declared_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Valor Declarado")
    is_fragile = models.BooleanField(default=False, verbose_name="Frágil?")
    requires_signature = models.BooleanField(default=True, verbose_name="Exige Assinatura?")
    item_notes = models.TextField(blank=True, verbose_name="Observações do Item")

    def clean(self):
        if self.status in [self.ItemStatus.COLETADO, self.ItemStatus.TRANSFERIDO]:
            if not self.posse_atual:
                raise ValidationError(f"Erro de consistência: Um item '{self.get_status_display()}' precisa estar vinculado à posse de um motoboy.")
                
        elif self.status in [self.ItemStatus.NAO_COLETADO, self.ItemStatus.ENTREGUE, self.ItemStatus.RETORNADO, self.ItemStatus.EXTRAVIADO]:
            if self.posse_atual:
                raise ValidationError(f"Erro de consistência: Um item '{self.get_status_display()}' não pode continuar no baú/posse de um motoboy.")

    def __str__(self):
        return f"{self.total_quantity}x {self.description}"


class OSDestination(models.Model):
    order = models.ForeignKey(ServiceOrder, on_delete=models.CASCADE, related_name='destinations')
    
    destination_name = models.CharField(max_length=100, verbose_name="Nome Destinatário")
    destination_phone = models.CharField(max_length=20, verbose_name="Telefone Destino")
    destination_street = models.CharField(max_length=255, verbose_name="Rua (Destino)")
    destination_number = models.CharField(max_length=20, verbose_name="Número (Destino)")
    destination_complement = models.CharField(max_length=100, blank=True, verbose_name="Complemento (Destino)")
    destination_district = models.CharField(max_length=100, verbose_name="Bairro (Destino)")
    destination_state = models.CharField(max_length=2, blank=True, null=True, verbose_name="UF (Destino)")
    destination_city = models.CharField(max_length=100, verbose_name="Cidade (Destino)")
    destination_zip_code = models.CharField(max_length=10, verbose_name="CEP (Destino)")
    destination_reference = models.CharField(max_length=255, blank=True, verbose_name="Ponto de Referência (Destino)")
    delivery_value = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor da Entrega")
    destination_notes = models.TextField(blank=True, verbose_name="Observações")

    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora Entrega Real")
    geo_delivery_lat = models.CharField(max_length=50, blank=True, verbose_name="Geo Entrega (Lat)")
    geo_delivery_lng = models.CharField(max_length=50, blank=True, verbose_name="Geo Entrega (Lng)")
    proof_photo = models.ImageField(upload_to='proofs/', null=True, blank=True, verbose_name="Foto Comprovação")
    receiver_name = models.CharField(max_length=100, blank=True, verbose_name="Nome de quem recebeu")
    receiver_signature = models.ImageField(upload_to='signatures/', null=True, blank=True, verbose_name="Assinatura Digital")
    confirmation_code = models.CharField(max_length=6, blank=True, verbose_name="Código OTP")

    def __str__(self):
        return f"Destino: {self.destination_name} - {self.destination_district}"


class ItemDistribution(models.Model):
    item = models.ForeignKey(OSItem, on_delete=models.CASCADE, related_name='distributions')
    destination = models.ForeignKey(OSDestination, on_delete=models.CASCADE, related_name='distributed_items')
    quantity_allocated = models.PositiveIntegerField(verbose_name="Qtd Alocada para este destino")

    def __str__(self):
        return f"{self.quantity_allocated}x de {self.item.description} para {self.destination.destination_name}"


class OrderStatusLog(models.Model):
    order = models.ForeignKey(ServiceOrder, on_delete=models.CASCADE, related_name='logs')
    status_anterior = models.CharField(max_length=50)
    status_novo = models.CharField(max_length=50)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.order.os_number}: {self.status_anterior} -> {self.status_novo}"

class RouteStop(models.Model):
    """
    Define um Ponto de Parada na rota de um motoboy. 
    Uma OS com 1 coleta e 2 entregas vai gerar 3 RouteStops que o despachante pode reordenar livremente.
    """
    class StopType(models.TextChoices):
        COLLECTION = 'COLETA', 'Coleta na Origem'
        DELIVERY = 'ENTREGA', 'Entrega no Destino'
        TRANSFER = 'TRANSFERENCIA', 'Transferência de Carga'
        RETURN = 'DEVOLUCAO', 'Devolução'

    # Faltava esta classe!
    class StopStatus(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em Andamento'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'
        COM_OCORRENCIA = 'COM_OCORRENCIA', 'Com Ocorrência'
        AGUARDANDO_DECISAO = 'AGUARDANDO_DECISAO', 'Aguardando Decisão'
        CANCELADA = 'CANCELADA', 'Cancelada'

    motoboy = models.ForeignKey('logistics.MotoboyProfile', on_delete=models.CASCADE, related_name='route_stops', null=True, blank=True)
    service_order = models.ForeignKey(ServiceOrder, on_delete=models.CASCADE, related_name='stops')
    
    stop_type = models.CharField(max_length=20, choices=StopType.choices)
    destination = models.ForeignKey(OSDestination, on_delete=models.CASCADE, null=True, blank=True)
    sequence = models.PositiveIntegerField(default=0)
    
    status = models.CharField(max_length=25, choices=StopStatus.choices, default=StopStatus.PENDENTE)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    bloqueia_proxima = models.BooleanField(default=True, help_text="Se True, o motoboy não pode avançar sem resolver esta parada.")
    
    # Estes dois campos faltavam e a função __str__ precisa deles!
    is_failed = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=255, blank=True)
    custom_address = models.CharField(max_length=255, blank=True, help_text="Endereço para Devolução ou Ponto de Encontro")
    custom_complement = models.CharField(max_length=255, blank=True, help_text="Complemento da Devolução")

    def clean(self):
        if self.pk:
            old_instance = RouteStop.objects.get(pk=self.pk)
            if old_instance.is_completed and not self.is_completed:
                raise ValidationError("Não é permitido reabrir uma parada que já foi concluída.")

    class Meta:
        ordering = ['motoboy', 'sequence']

    def __str__(self):
        if self.stop_type == 'COLETA':
            tipo = "Coleta"
            local = self.service_order.origin_name
        elif self.stop_type == 'ENTREGA':
            tipo = "Entrega"
            local = self.destination.destination_name if self.destination else "Destino Indefinido"
        elif self.stop_type == 'TRANSFERENCIA':
            tipo = "Transferência"
            local = self.custom_address if self.custom_address else "Ponto de Encontro" 
        elif self.stop_type == 'DEVOLUCAO':
            tipo = "Devolução"
            local = self.custom_address if self.custom_address else "Local de Devolução"
        else:
            tipo = "Desconhecido"
            local = "Desconhecido"
            
        return f"{self.sequence}º Parada: {tipo} em {local} (OS {self.service_order.os_number})"

    def get_panel_display_address(self):
        """Endereço limpo para exibir no painel (sem prefixos como 'Devolver em:', 'AGUARDE...')."""
        if not self.custom_address:
            return "Endereço não informado"
        addr = self.custom_address
        if addr.startswith("Devolver em: "):
            return addr[12:].strip()
        if "AGUARDE O RESGATE AQUI:" in addr:
            return addr.split("AGUARDE O RESGATE AQUI:", 1)[-1].strip()
        if "Resgatar carga(s) de colega acidentado:" in addr:
            return addr.split("Resgatar carga(s) de colega acidentado:", 1)[-1].strip()
        return addr

    def get_panel_activity_label(self):
        """Rótulo do que o motoboy está fazendo, para a coluna 'Em Atendimento'."""
        if self.stop_type == 'COLETA':
            return ('danger', 'Fazendo coleta em:')
        if self.stop_type == 'ENTREGA':
            return ('success', 'Entregando em:')
        if self.stop_type == 'DEVOLUCAO':
            return ('info', 'Devolvendo para:')
        if self.stop_type == 'TRANSFERENCIA':
            if self.custom_address and 'AGUARDE' in self.custom_address:
                return ('warning', 'Aguardando outro motoboy buscar itens neste local:')
            return ('warning', 'Resgatando itens de colega no local:')
        return ('secondary', 'Em atendimento:')

    
class Occurrence(models.Model):
    class Causa(models.TextChoices):
        AUSENTE = 'AUSENTE', 'Destinatário Ausente'
        NAO_LOCALIZADO = 'NAO_LOCALIZADO', 'Endereço não localizado'
        RECUSA = 'RECUSA', 'Mercadoria recusada'
        ACIDENTE = 'ACIDENTE', 'Veículo avariado / Acidente'
        FECHADO = 'FECHADO', 'Local Fechado'
        OUTRO = 'OUTRO', 'Outro Motivo'

    class Urgencia(models.TextChoices):
        BAIXA = 'BAIXA', 'Baixa'
        MEDIA = 'MEDIA', 'Média'
        ALTA = 'ALTA', 'Alta (Crítico)'

    parada = models.ForeignKey(RouteStop, on_delete=models.CASCADE, related_name='ocorrencias')
    service_order = models.ForeignKey(ServiceOrder, on_delete=models.CASCADE, related_name='ocorrencias')
    motoboy = models.ForeignKey('logistics.MotoboyProfile', on_delete=models.CASCADE)
    
    causa = models.CharField(max_length=20, choices=Causa.choices)
    subtipo_tags = models.JSONField(blank=True, null=True, help_text="Ex: ['Sem internet', 'Área de risco']")
    observacao = models.TextField(blank=True)
    
    tentativas_contato = models.PositiveIntegerField(default=0)
    evidencia_foto = models.ImageField(upload_to='ocorrencias/evidencias/', null=True, blank=True)
    
    urgencia = models.CharField(max_length=10, choices=Urgencia.choices, default=Urgencia.MEDIA)
    criado_em = models.DateTimeField(auto_now_add=True)
    resolvida = models.BooleanField(default=False)

    def __str__(self):
        return f"Ocorrência {self.get_causa_display()} na OS {self.service_order.os_number}"

    def get_local_address(self):
        """Endereço do local da parada onde ocorreu o problema (para exibir no modal de decisão)."""
        stop = self.parada
        if stop.stop_type == 'COLETA' and self.service_order:
            o = self.service_order
            addr = f"{o.origin_street or ''}, {o.origin_number or ''} - {o.origin_district or ''}"
            return addr.strip(' ,-') or '—'
        if stop.stop_type == 'ENTREGA' and stop.destination:
            d = stop.destination
            addr = f"{d.destination_street or ''}, {d.destination_number or ''} - {d.destination_district or ''}"
            return addr.strip(' ,-') or '—'
        return stop.get_panel_display_address() or '—'


class DispatcherDecision(models.Model):
    class Acao(models.TextChoices):
        REAGENDAR = 'REAGENDAR', 'Reagendar tentativa'
        ALTERAR_ENDERECO = 'ALTERAR_ENDERECO', 'Alterar endereço'
        AUTORIZAR_ALTERNATIVA = 'AUTORIZAR_ALTERNATIVA', 'Autorizar entrega alternativa'
        RETORNAR = 'RETORNAR', 'Retornar mercadoria'
        CANCELAR = 'CANCELAR', 'Cancelar OS/Entrega'
        TRANSFERIR_MOTOBOY = 'TRANSFERIR_MOTOBOY', 'Transferir para outro motoboy'
        CRIAR_PARADA = 'CRIAR_PARADA', 'Criar parada extra'
        VOLTAR_FILA = 'VOLTAR_FILA', 'Voltar para a Fila'

    occurrence = models.OneToOneField(Occurrence, on_delete=models.CASCADE, related_name='decisao')
    acao = models.CharField(max_length=30, choices=Acao.choices)
    detalhes = models.TextField(blank=True)
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    decidido_em = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Decisão {self.get_acao_display()} por {self.decidido_por}"