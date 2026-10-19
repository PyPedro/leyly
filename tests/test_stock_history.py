import json

import pytest
from sqlalchemy import create_engine, inspect, text
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Admin, Produto, Usuario


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{(tmp_path / 'stock-history.sqlite').as_posix()}")
    monkeypatch.delenv('UPLOAD_DIR', raising=False)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = Admin(
            email='estoque-admin@leyly.com',
            senha=generate_password_hash('senha-admin-estoque'),
        )
        usuario = Usuario(
            nome='Cliente Estoque',
            email='cliente-estoque@leyly.com',
            senha=generate_password_hash('senha-cliente-estoque'),
            whatsapp='81999999999',
        )
        produto = Produto(
            codigo='EST-01',
            nome='Produto de estoque',
            preco=100,
            etiqueta='ESTOQUE',
            imagem_url='img/default.jpg',
            estoque_p=10,
            estoque_m=10,
            estoque_g=10,
            estoque_gg=10,
            variantes=json.dumps([{
                'cor': 'Preto',
                'tamanhos': [{'nome': 'P', 'estoque': 10, 'preco': 100}],
            }]),
        )
        db.session.add_all([admin, usuario, produto])
        db.session.commit()
        usuario_id = usuario.id
        admin_id = admin.id
    yield app, usuario_id, admin_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _login_admin(client, admin_id):
    with client.session_transaction() as sessao:
        sessao['admin_logado'] = True
        sessao['admin_id'] = admin_id


def test_reserva_de_pedido_grava_historico_da_variacao(app):
    aplicacao, _, admin_id = app
    with aplicacao.test_client() as cliente:
        login = cliente.post('/api/login', json={
            'nome': 'Cliente Estoque',
            'whatsapp': '81999999999',
        })
        assert login.get_json()['sucesso'] is True
        resposta_sync = cliente.post('/api/carrinho/sync', json={
            'frete_tipo': 'Retirada em Surubim',
            'carrinho': [{
                'id': 1,
                'nome': 'Produto de estoque',
                'tamanho': 'P',
                'cor': 'Preto',
                'preco': 100,
                'quantidade': 2,
            }],
        })
        assert resposta_sync.get_json()['sucesso'] is True

        _login_admin(cliente, admin_id)
        resposta = cliente.get('/api/admin/produtos/1/estoque/historico?cor=Preto&tamanho=P')

    historico = resposta.get_json()['historico']
    assert resposta.status_code == 200
    assert len(historico) == 1
    assert historico[0]['estoque_anterior'] == 10
    assert historico[0]['qtde_alterada'] == -2
    assert historico[0]['estoque_novo'] == 8
    assert historico[0]['usuario'] == 'PEDIDO'
    assert 'PEDIDO DE ID' in historico[0]['descricao']
    assert historico[0]['data_criacao']


def test_ajuste_manual_grava_valores_e_usuario_no_historico(app):
    aplicacao, _, admin_id = app
    with aplicacao.test_client() as cliente:
        _login_admin(cliente, admin_id)
        ajuste = cliente.post('/api/admin/produtos/atualizar', json={'id': 1, 'p': 15})
        historico = cliente.get('/api/admin/produtos/1/estoque/historico?cor=GERAL&tamanho=P')

    movimento = historico.get_json()['historico'][0]
    assert ajuste.status_code == 200
    assert movimento['estoque_anterior'] == 10
    assert movimento['qtde_alterada'] == 5
    assert movimento['estoque_novo'] == 15
    assert movimento['usuario'] == 'estoque-admin@leyly.com'


def test_historico_requer_cor_e_tamanho_da_variacao(app):
    aplicacao, _, admin_id = app
    with aplicacao.test_client() as cliente:
        _login_admin(cliente, admin_id)
        resposta = cliente.get('/api/admin/produtos/1/estoque/historico?cor=Preto')

    assert resposta.status_code == 400
    assert resposta.get_json()['sucesso'] is False


def test_migracao_preserva_movimentos_anteriores_e_cria_campos_de_historico(tmp_path, monkeypatch):
    arquivo_banco = tmp_path / 'estoque-legado.sqlite'
    engine = create_engine(f"sqlite:///{arquivo_banco.as_posix()}")
    with engine.begin() as conexao:
        conexao.execute(text(
            'CREATE TABLE estoque_movimento ('
            'id INTEGER PRIMARY KEY, produto_id INTEGER NOT NULL, pedido_id INTEGER, usuario_id INTEGER, '
            'cor VARCHAR(80) NOT NULL, tamanho VARCHAR(50) NOT NULL, quantidade INTEGER NOT NULL, '
            'tipo VARCHAR(20) NOT NULL, origem VARCHAR(30) NOT NULL, motivo VARCHAR(200), '
            'data_movimento DATETIME NOT NULL)'
        ))
        conexao.execute(text(
            "INSERT INTO estoque_movimento "
            "(id, produto_id, cor, tamanho, quantidade, tipo, origem, data_movimento) "
            "VALUES (1, 5, 'Preto', 'P', 2, 'SAIDA', 'PEDIDO', '2026-10-18 12:00:00')"
        ))
    engine.dispose()
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{arquivo_banco.as_posix()}")
    monkeypatch.delenv('UPLOAD_DIR', raising=False)

    app = create_app()
    with app.app_context():
        colunas = {coluna['name'] for coluna in inspect(db.engine).get_columns('estoque_movimento')}
        movimento = db.session.execute(text(
            'SELECT data_criacao FROM estoque_movimento WHERE id = 1'
        )).one()

    assert {
        'descricao',
        'usuario',
        'estoque_anterior',
        'qtde_alterada',
        'estoque_novo',
        'data_criacao',
    }.issubset(colunas)
    assert movimento.data_criacao == '2026-10-18 12:00:00'
