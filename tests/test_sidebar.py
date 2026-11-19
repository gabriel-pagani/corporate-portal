import re
from pathlib import Path

from django.contrib.staticfiles import finders


def read_static(path):
    return Path(finders.find(path)).read_text(encoding='utf-8')


def css_rule(style, selector):
    # Junta todos os blocos do seletor, já que alguns arquivos o declaram em mais de um lugar
    return '\n'.join(re.findall(r'(?:^|\n)' + re.escape(selector) + r'\s*\{([^}]*)\}', style))


def test_page_height_follows_the_visible_screen():
    # No celular o 100vh passa da área visível e a barra do navegador cobria o botão de minimizar
    body = css_rule(read_static('global/css/sidebar.css'), 'body')
    assert 'height: 100dvh' in body
    # O 100vh fica antes, de reserva para navegadores sem dvh
    assert body.index('height: 100vh') < body.index('height: 100dvh')


def test_only_the_menu_shrinks_when_the_screen_is_short():
    style = read_static('global/css/sidebar.css')
    assert 'min-height: 0' in css_rule(style, '.menu')
    for selector in ('.sidebar', '.logo', '.bottom'):
        assert 'flex-shrink: 0' in css_rule(style, selector)


def test_collapsed_dashboards_menu_keeps_scrolling():
    # Sem rolagem no menu minimizado, muitos setores empurravam o botão de minimizar para fora da tela
    style = read_static('app/css/dashboards.css')
    assert not re.search(r'\.sidebar\.collapsed \.menu\s*\{[^}]*overflow:\s*visible', style)
    # O dropdown sai da sidebar por ser fixo na tela, posicionado na altura do setor
    assert 'position: fixed' in css_rule(style, '.sidebar.collapsed .submenu')
    script = read_static('app/js/dashboards.js')
    assert 'sectorHeader.getBoundingClientRect().top' in script


def test_pages_with_the_sidebar_use_the_visible_height():
    for path, selector in (('app/css/home.css', '.main-content'), ('app/css/library.css', '.main-content.library')):
        assert 'height: 100dvh' in css_rule(read_static(path), selector)
