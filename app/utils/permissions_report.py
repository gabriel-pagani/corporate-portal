from io import BytesIO
from xml.sax.saxutils import escape
from django.apps import apps
from django.contrib.auth.models import Permission
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from app.models import Dashboard


def describe_permission(permission):
    content_type = permission.content_type
    model = content_type.model_class()
    return {
        'app': apps.get_app_config(content_type.app_label).verbose_name,
        'model': model._meta.verbose_name if model else content_type.model,
        'name': permission.name,
        'codename': f'{content_type.app_label}.{permission.codename}',
    }


def user_permissions_report(users):
    """O que cada usuário pode fazer no portal, e de onde vem cada acesso."""
    users = users.prefetch_related(
        'user_permissions__content_type',
        'groups__permissions__content_type',
        'groups__perfil__dashboards',
        'dashboards',
    ).order_by('username')
    all_dashboards = list(Dashboard.objects.select_related('sector'))
    all_permissions = list(Permission.objects.select_related('content_type'))

    report = []
    for user in users:
        groups = list(user.groups.all())

        # A mesma permissão pode chegar direto e por mais de um grupo: todas as
        # origens aparecem, para se saber o que tirar para revogar o acesso
        permissions = {}
        for permission in user.user_permissions.all():
            permissions.setdefault(permission, []).append('Direta')
        for group in groups:
            for permission in group.permissions.all():
                permissions.setdefault(permission, []).append(f'Grupo {group.name}')
        # O superusuário passa em qualquer verificação de permissão, listada ou não
        if user.is_superuser:
            for permission in all_permissions:
                permissions.setdefault(permission, []).append('Superusuário')

        rows = sorted(
            ({**describe_permission(permission), 'sources': sources} for permission, sources in permissions.items()),
            key=lambda row: (row['app'], str(row['model']), row['name']),
        )

        # As mesmas regras do get_user_dashboards, mas guardando a origem de cada acesso
        sees_all = user.is_superuser or any(row['codename'] == 'app.view_all_dashboards' for row in rows)
        dashboards = {}
        for dashboard in user.dashboards.all():
            dashboards.setdefault(dashboard, []).append('Direto')
        for group in groups:
            try:
                profile_dashboards = group.perfil.dashboards.all()
            except ObjectDoesNotExist:
                continue
            for dashboard in profile_dashboards:
                dashboards.setdefault(dashboard, []).append(f'Grupo {group.name}')
        if sees_all:
            origin = 'Superusuário' if user.is_superuser else 'Ver todos os dashboards'
            for dashboard in all_dashboards:
                dashboards.setdefault(dashboard, []).append(origin)

        report.append({
            'user': user,
            'groups': [group.name for group in groups],
            'permissions': rows,
            'dashboards': sorted(
                ({'title': dashboard.title, 'sources': sources} for dashboard, sources in dashboards.items()),
                key=lambda row: row['title'],
            ),
        })
    return report


STYLES = getSampleStyleSheet()
TITLE = ParagraphStyle('ReportTitle', parent=STYLES['Title'], alignment=0, fontSize=16, spaceAfter=2)
SUBTITLE = ParagraphStyle('ReportSubtitle', parent=STYLES['Normal'], fontSize=9, textColor=colors.HexColor('#666666'))
USER = ParagraphStyle('ReportUser', parent=STYLES['Heading2'], fontSize=13, spaceBefore=14, spaceAfter=4)
SECTION = ParagraphStyle('ReportSection', parent=STYLES['Heading4'], fontSize=10, spaceBefore=8, spaceAfter=3)
TEXT = ParagraphStyle('ReportText', parent=STYLES['Normal'], fontSize=9, leading=12)
INACTIVE_USER = ParagraphStyle('ReportInactiveUser', parent=USER, textColor=colors.HexColor('#a32d2d'))
CELL = ParagraphStyle('ReportCell', parent=TEXT, fontSize=8, leading=10)
HEADER_CELL = ParagraphStyle('ReportHeaderCell', parent=CELL, textColor=colors.white, fontName='Helvetica-Bold')


def text(value):
    # O que vem do banco entra na marcação da ReportLab: um & ou < no nome quebraria o PDF
    return escape(str(value))


def table(header, rows, widths):
    data = [[Paragraph(text(title), HEADER_CELL) for title in header]]
    data += [[Paragraph(text(value), CELL) for value in row] for row in rows]
    grid = Table(data, colWidths=widths, repeatRows=1)
    grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#333333')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return grid


def yes_no(value):
    return 'Sim' if value else 'Não'


def user_section(item):
    user = item['user']
    name = user.get_full_name()
    last_login = timezone.localtime(user.last_login).strftime('%d/%m/%Y %H:%M') if user.last_login else 'nunca'
    flags = (
        f'Ativo: {yes_no(user.is_active)} · Membro da equipe: {yes_no(user.is_staff)} · Super usuário: {yes_no(user.is_superuser)}'
    )

    flowables = [
        Paragraph(text(f'{user.username} - {name}' if name else user.username), USER if user.is_active else INACTIVE_USER),
        Paragraph(text(flags), TEXT),
    ]

    flowables += [Paragraph('Grupos', SECTION), Paragraph(text(', '.join(item['groups']) or 'Nenhum grupo.'), TEXT)]

    # Os títulos não ficam sozinhos no fim da página, separados da tabela: só se
    # pula de página quando não cabem nem as primeiras linhas. Um KeepTogether com
    # a tabela inteira mandaria tudo para a página seguinte e deixaria esta vazia
    permissions = [CondPageBreak(3 * cm), Paragraph('Permissões', SECTION)]
    if item['permissions']:
        permissions.append(table(
            ['Aplicação', 'Modelo', 'Permissão', 'Código', 'Origem'],
            [
                [row['app'], str(row['model']).capitalize(), row['name'], row['codename'], ', '.join(row['sources'])]
                for row in item['permissions']
            ],
            [4 * cm, 4.5 * cm, 6.5 * cm, 5.5 * cm, 6.2 * cm],
        ))
    else:
        permissions.append(Paragraph('Nenhuma permissão atribuída diretamente ou por grupo.', TEXT))

    dashboards = [CondPageBreak(3 * cm), Paragraph('Dashboards', SECTION)]
    if item['dashboards']:
        dashboards.append(table(
            ['Dashboard', 'Origem'],
            [[row['title'], ', '.join(row['sources'])] for row in item['dashboards']],
            [14 * cm, 12.7 * cm],
        ))
    else:
        dashboards.append(Paragraph('Nenhum dashboard.', TEXT))

    return [CondPageBreak(6 * cm)] + flowables + permissions + dashboards


def permissions_report_pdf(report, generated_by):
    generated_at = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    buffer = BytesIO()

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawString(document.leftMargin, 1 * cm, f'Relatório de permissões · {generated_at}')
        canvas.drawRightString(document.pagesize[0] - document.rightMargin, 1 * cm, f'Página {document.page}')
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title='Relatório de permissões',
        author=generated_by,
    )
    story = [
        Paragraph('Relatório de permissões', TITLE),
        Paragraph(text(f'Gerado em {generated_at} por {generated_by} · {len(report)} usuário(s)'), SUBTITLE),
        Spacer(1, 4),
    ]
    for item in report:
        story += user_section(item)

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
