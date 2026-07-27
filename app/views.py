from app.models import Employee
from django.shortcuts import render


def employees_view(request):
    data = [
        {
            'name': employee.get_display_name(),
            'number': employee.number or '',
            'sector': employee.sector.name if employee.sector else '',
            'machine': employee.machine or '',
        }
        for employee in Employee.objects.select_related('sector', 'user').all()
    ]

    return render(request, 'app/employees.html', {
        'data': data
    })
