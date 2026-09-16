from .models import ConfiguracionEmpresa

def empresa_config(request):
    config = ConfiguracionEmpresa.objects.first()
    return {
        'empresa': config
    }