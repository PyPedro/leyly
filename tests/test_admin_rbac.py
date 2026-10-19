import pytest
from sqlalchemy import create_engine, inspect, text
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Admin


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
        assert client.get('/api/admin/dashboard').status_code == 403
        assert client.get('/api/admin/produtos').status_code == 200
        assert client.post('/api/admin/produtos/atualizar', json={}).status_code == 403


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
