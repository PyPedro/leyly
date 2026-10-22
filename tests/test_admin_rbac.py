import json

import pytest
from sqlalchemy import create_engine, inspect, text
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Admin, Pedido, Produto, Usuario


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
        db.session.add_all([
            Admin(
                email='admin@leyly.com',
                senha=generate_password_hash('senha-admin-123'),
                tipo_acesso='admin',
            ),
            Admin(
                email='vendedora@leyly.com',
                senha=generate_password_hash('senha-vendedora-123'),
                tipo_acesso='vendedora',
            ),
            Admin(
                email='perfil-invalido@leyly.com',
                senha=generate_password_hash('senha-invalida-123'),
                tipo_acesso='perfil-invalido',
            ),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _login(client, email, senha):
    return client.post('/admin/login', data={'email': email, 'senha': senha})


def test_vendedora_e_redirecionada_para_expedicao_e_so_ve_pedidos(app):
    with app.test_client() as client:
        login = _login(client, 'vendedora@leyly.com', 'senha-vendedora-123')

        assert login.status_code == 302
        assert login.headers['Location'].endswith('/admin?pagina=pedidos')

        pagina = client.get('/admin?pagina=pedidos')
        html = pagina.get_data(as_text=True)
        assert pagina.status_code == 200
        assert 'id="page-pedidos" class="page-section active"' in html
        assert 'id="page-dashboard"' not in html
        assert 'id="page-estoque"' not in html
        assert 'Dashboard</button>' not in html
        assert 'Estoque</button>' not in html
        assert 'id="modalNovoProduto"' not in html
        assert 'id="modalPedidoDetalhes"' in html


def test_vendedora_so_acessa_rotas_de_expedicao(app):
    with app.test_client() as client:
        _login(client, 'vendedora@leyly.com', 'senha-vendedora-123')

        assert client.get('/admin?pagina=dashboard').headers['Location'].endswith('/admin?pagina=pedidos')
        assert client.get('/api/admin/pedidos').status_code == 200
        assert client.get('/admin/pedidos/imprimir-lote?ids=1').status_code == 404
        assert client.get('/api/admin/dashboard').status_code == 403
        assert client.get('/api/admin/produtos').status_code == 200
        assert client.post('/api/admin/produtos/atualizar', json={}).status_code == 403


def test_admin_pode_exportar_pedidos_em_pdf_com_foto_e_preco_registrado(app, monkeypatch):
    with app.app_context():
        usuario = Usuario(
            nome='Cliente do PDF',
            email='cliente-pdf@leyly.com',
            senha='senha',
            whatsapp='81999999999',
        )
        db.session.add(usuario)
        db.session.flush()
        produto = Produto(
            nome='Produto de teste',
            preco=100.00,
            etiqueta='TESTE',
            imagem_url='catalogo/produto.jpg',
        )
        db.session.add(produto)
        db.session.flush()
        pedido = Pedido(
            usuario_id=usuario.id,
            nome_cliente='Cliente do PDF',
            status='PAGO',
            itens=json.dumps([{
                'id': produto.id,
                'nome': 'Produto de teste',
                'codigo': 'REF-01',
                'cor': 'Roxo',
                'tamanho': 'M',
                'quantidade': 2,
                'preco': 101.00,
            }]),
            valor_total=202.00,
        )
        outro_pedido = Pedido(
            usuario_id=usuario.id,
            nome_cliente='Cliente do PDF',
            status='PAGO',
            itens=pedido.itens,
            valor_total=202.00,
        )
        db.session.add_all([pedido, outro_pedido])
        db.session.commit()
        pedido_id = pedido.id
        outro_pedido_id = outro_pedido.id

    monkeypatch.setattr(
        'app.routes.imagem_disponivel',
        lambda caminho: caminho == 'catalogo/produto.thumb.webp',
    )

    with app.test_client() as client:
        _login(client, 'admin@leyly.com', 'senha-admin-123')

        resposta = client.get(f'/admin/pedidos/imprimir-lote?ids={pedido_id},{outro_pedido_id}')
        html = resposta.get_data(as_text=True)

        assert resposta.status_code == 200
        assert 'html2pdf' not in html
        assert html.count('class="pedido-pdf break-inside-avoid page-break-after-always"') == 2
        assert 'page-break-after: always; break-after: page;' in html
        assert 'Imprimir Pedidos (Brother / PDF)' in html
        assert 'window.print()' in html
        assert 'class="w-full table-fixed break-words text-[11px]"' in html
        assert 'R$ 101,00' in html
        assert 'R$ 202,00' in html
        assert 'R$ 102,01' not in html
        assert 'src="/static/catalogo/produto.thumb.webp"' in html
        assert 'crossorigin="anonymous"' in html
        assert 'class="w-full max-w-[800px] mx-auto bg-white text-black p-4"' in html


def test_exportacao_em_lote_rejeita_ids_invalidos_ou_inexistentes(app):
    with app.test_client() as client:
        _login(client, 'admin@leyly.com', 'senha-admin-123')

        assert client.get('/admin/pedidos/imprimir-lote?ids=1,abc').status_code == 400
        assert client.get('/admin/pedidos/imprimir-lote?ids=999').status_code == 404


def test_marcar_pedidos_impressos_em_lote_move_pedidos_pagos_para_separacao(app):
    with app.app_context():
        usuario = Usuario(
            nome='Cliente de separação',
            email='cliente-separacao@leyly.com',
            senha='senha',
            whatsapp='81999999999',
        )
        db.session.add(usuario)
        db.session.flush()
        pedido = Pedido(
            usuario_id=usuario.id,
            status='PAGO',
            itens=json.dumps([{'preco': 400, 'quantidade': 1}]),
        )
        db.session.add(pedido)
        db.session.commit()
        pedido_id = pedido.id

    with app.test_client() as client:
        _login(client, 'admin@leyly.com', 'senha-admin-123')

        resposta = client.post('/admin/pedidos/lote/marcar-impresso', json={'ids': [pedido_id]})

    assert resposta.status_code == 200
    assert resposta.get_json() == {'success': True}
    with app.app_context():
        pedido_atualizado = db.session.get(Pedido, pedido_id)
        assert pedido_atualizado.status == 'SEPARACAO'
        assert pedido_atualizado.numero_separacao is not None


def test_marcar_pedidos_impressos_em_lote_rejeita_ids_invalidos(app):
    with app.test_client() as client:
        _login(client, 'admin@leyly.com', 'senha-admin-123')

        assert client.post('/admin/pedidos/lote/marcar-impresso', json={'ids': []}).status_code == 400
        assert client.post('/admin/pedidos/lote/marcar-impresso', json={'ids': ['inválido']}).status_code == 400


def test_admin_mantem_acesso_ao_dashboard_e_pode_criar_vendedora(app):
    with app.test_client() as client:
        _login(client, 'admin@leyly.com', 'senha-admin-123')

        pagina = client.get('/admin')
        assert pagina.status_code == 200
        assert 'id="page-dashboard" class="page-section active"' in pagina.get_data(as_text=True)
        assert client.get('/api/admin/dashboard').status_code == 200

        resposta = client.post('/api/admin/admins', json={
            'email': 'nova-vendedora@leyly.com',
            'senha': 'senha-nova-vendedora',
            'tipo_acesso': 'vendedora',
        })
        assert resposta.status_code == 201
        assert resposta.get_json()['tipo_acesso'] == 'vendedora'


def test_perfil_desconhecido_recebe_403_sem_redirecionamento(app):
    with app.test_client() as client:
        _login(client, 'perfil-invalido@leyly.com', 'senha-invalida-123')

        assert client.get('/admin').status_code == 403
        assert client.get('/api/admin/pedidos').status_code == 403


def test_migracao_adiciona_perfil_padrao_a_tabela_admin_existente(tmp_path, monkeypatch):
    arquivo_banco = tmp_path / 'admin-antigo.sqlite'
    engine = create_engine(f'sqlite:///{arquivo_banco.as_posix()}')
    with engine.begin() as conexao:
        conexao.execute(text(
            'CREATE TABLE admin (id INTEGER PRIMARY KEY, email VARCHAR(120) NOT NULL UNIQUE, senha VARCHAR(200) NOT NULL)'
        ))
        conexao.execute(text(
            "INSERT INTO admin (email, senha) VALUES ('admin-existente@leyly.com', 'hash')"
        ))
    engine.dispose()
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{arquivo_banco.as_posix()}')

    app = create_app()
    with app.app_context():
        colunas = {coluna['name']: coluna for coluna in inspect(db.engine).get_columns('admin')}
        assert 'tipo_acesso' in colunas
        assert Admin.query.filter_by(email='admin-existente@leyly.com').one().tipo_acesso == 'admin'
