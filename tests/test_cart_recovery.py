import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app import create_app, db
from app.models import Admin, Pedido, Produto, Usuario
from app.routes import enviar_notificacao_carrinho, limpar_carrinhos_abandonados


@pytest.fixture
def recovery_app(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{(tmp_path / 'cart-recovery.sqlite').as_posix()}")
    monkeypatch.delenv('UPLOAD_DIR', raising=False)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = Admin(
            email='vendedora-recuperacao@leyly.com',
            senha='hash',
            tipo_acesso='vendedora',
        )
        usuario = Usuario(
            nome='Cliente Recuperação',
            email='cliente-recuperacao@leyly.com',
            senha='hash',
            whatsapp='81999999999',
        )
        produto = Produto(
            codigo='REF-32',
            nome='Produto de recuperação',
            preco=32,
            etiqueta='TESTE',
            imagem_url='img/teste.jpg',
            ativo=True,
            variantes=json.dumps([{
                'cor': 'Preto',
                'tamanhos': [
                    {'nome': 'P', 'estoque': 10, 'preco': 32},
                    {'nome': 'M', 'estoque': 10, 'preco': 32},
                ],
            }]),
        )
        db.session.add_all([admin, usuario, produto])
        db.session.commit()
        ids = (admin.id, usuario.id, produto.id)
    yield app, ids
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _login_vendedora(client, admin_id):
    with client.session_transaction() as sessao:
        sessao['admin_logado'] = True
        sessao['admin_id'] = admin_id


def _novo_pedido(usuario_id, produto_id, minutos, status='ABERTO'):
    agora = datetime.utcnow()
    return Pedido(
        usuario_id=usuario_id,
        criado_em=agora - timedelta(minutes=minutos),
        data_atualizacao=agora,
        status=status,
        itens=json.dumps([{
            'id': produto_id,
            'nome': 'Produto de recuperação',
            'referencia': 'REF-32',
            'tamanho': 'P',
            'cor': 'Preto',
            'preco': 32.32,
            'quantidade': 1,
        }]),
        valor_total=32.32,
    )


def test_busca_admin_limita_a_dez_e_retorna_preco_com_acrescimo(recovery_app):
    app, (admin_id, _, produto_id) = recovery_app
    with app.app_context():
        for numero in range(10):
            db.session.add(Produto(
                codigo=f'REF-OUTRO-{numero}',
                nome=f'Produto adicional {numero}',
                preco=32,
                etiqueta='TESTE',
                imagem_url='img/teste.jpg',
                ativo=True,
                variantes=json.dumps([{
                    'cor': 'Azul',
                    'tamanhos': [{'nome': 'P', 'estoque': 1, 'preco': 32}],
                }]),
            ))
        db.session.commit()

    with app.test_client() as client:
        _login_vendedora(client, admin_id)
        resposta = client.get('/admin/api/buscar-produtos?q=Produto')
        resposta_referencia = client.get('/admin/api/buscar-produtos?q=REF-32')

    assert resposta.status_code == 200
    produtos = resposta.get_json()
    assert len(produtos) == 10
    assert resposta_referencia.status_code == 200
    produto_encontrado = resposta_referencia.get_json()[0]
    assert produto_encontrado['id'] == produto_id
    assert produto_encontrado['variantes'][0]['tamanhos'][0]['preco'] == 32.32


def test_edicao_de_pedido_grava_o_preco_com_acrescimo_em_itens_adicionados(recovery_app):
    app, (admin_id, usuario_id, produto_id) = recovery_app
    with app.app_context():
        pedido = _novo_pedido(usuario_id, produto_id, 5)
        db.session.add(pedido)
        db.session.commit()
        pedido_id = pedido.id

    with app.test_client() as client:
        _login_vendedora(client, admin_id)
        resposta = client.post('/api/admin/pedidos/editar', json={
            'id': pedido_id,
            'nome_cliente': 'Cliente Recuperação',
            'itens': [
                {'id': produto_id, 'cor': 'Preto', 'tamanho': 'P', 'quantidade': 1},
                {'id': produto_id, 'cor': 'Preto', 'tamanho': 'M', 'quantidade': 1},
            ],
        })

    assert resposta.status_code == 200
    with app.app_context():
        pedido_salvo = db.session.get(Pedido, pedido_id)
        itens = json.loads(pedido_salvo.itens)
        assert {item['tamanho']: item['preco'] for item in itens} == {'P': 32.32, 'M': 32.32}
        assert all(item['referencia'] == 'REF-32' for item in itens)

def test_sync_do_carrinho_ignora_preco_do_navegador_e_grava_preco_final(recovery_app):
    app, (_, usuario_id, produto_id) = recovery_app
    with app.app_context():
        usuario = db.session.get(Usuario, usuario_id)
        nome = usuario.nome
        whatsapp = usuario.whatsapp

    with app.test_client() as client:
        login = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        resposta = client.post('/api/carrinho/sync', json={
            'frete_tipo': 'Retirada em Surubim',
            'carrinho': [{
                'id': produto_id,
                'nome': 'Produto de recuperação',
                'tamanho': 'P',
                'cor': 'Preto',
                'preco': 1,
                'quantidade': 1,
            }],
        })

    assert login.get_json()['sucesso'] is True
    assert resposta.status_code == 200
    assert resposta.get_json()['carrinho'][0]['preco'] == 32.32
    with app.app_context():
        pedido = Pedido.query.one()
        assert json.loads(pedido.itens)[0]['preco'] == 32.32
        assert pedido.valor_total == 32.32


def test_recuperacao_filtra_vinte_minutos_e_bloqueia_whatsapp_ate_trinta(recovery_app):
    app, (admin_id, usuario_id, produto_id) = recovery_app
    with app.app_context():
        pedidos = [
            _novo_pedido(usuario_id, produto_id, 19),
            _novo_pedido(usuario_id, produto_id, 20),
            _novo_pedido(usuario_id, produto_id, 30, status='PAGAMENTO'),
        ]
        db.session.add_all(pedidos)
        db.session.commit()
        id_20, id_30 = pedidos[1].id, pedidos[2].id

    with app.test_client() as client:
        _login_vendedora(client, admin_id)
        pagina = client.get('/admin/carrinhos-abandonados')
        resposta = client.get('/api/admin/carrinhos-abandonados')
        bloqueado = client.post(f'/api/admin/carrinhos-abandonados/{id_20}/lembrete-enviado', json={})
        liberado = client.post(f'/api/admin/carrinhos-abandonados/{id_30}/lembrete-enviado', json={})

    assert pagina.status_code == 200
    assert 'id="page-carrinhos-abandonados" class="page-section active"' in pagina.get_data(as_text=True)
    assert resposta.status_code == 200
    carrinhos = resposta.get_json()['carrinhos']
    assert {carrinho['id'] for carrinho in carrinhos} == {id_20, id_30}
    assert all(carrinho['minutos_decorridos'] >= 20 for carrinho in carrinhos)
    assert bloqueado.status_code == 409
    assert liberado.status_code == 200
    with app.app_context():
        assert db.session.get(Pedido, id_30).lembrete_enviado is True


def test_limpeza_de_sessenta_minutos_so_expira_pedidos_abertos(recovery_app):
    app, (_, usuario_id, produto_id) = recovery_app
    with app.app_context():
        pedidos = [
            _novo_pedido(usuario_id, produto_id, 61, status=status)
            for status in ('ABERTO', 'PAGAMENTO', 'PAGO')
        ]
        for pedido in pedidos:
            pedido.data_atualizacao = datetime.utcnow() - timedelta(minutes=61)
        db.session.add_all(pedidos)
        produto = db.session.get(Produto, produto_id)
        variantes = json.loads(produto.variantes)
        variantes[0]['tamanhos'][0]['estoque'] = 7
        produto.variantes = json.dumps(variantes)
        db.session.commit()
        ids = [pedido.id for pedido in pedidos]

        limpar_carrinhos_abandonados()

        assert [db.session.get(Pedido, pedido_id).status for pedido_id in ids] == [
            'ABANDONADO',
            'PAGAMENTO',
            'PAGO',
        ]
        estoque = json.loads(db.session.get(Produto, produto_id).variantes)[0]['tamanhos'][0]['estoque']
        assert estoque == 8


def test_assinatura_onesignal_vincula_se_ao_usuario_e_envia_push(recovery_app):
    app, (_, usuario_id, _) = recovery_app
    with app.app_context():
        usuario = db.session.get(Usuario, usuario_id)
        pedido = _novo_pedido(usuario_id, 1, 30)
        db.session.add(pedido)
        db.session.commit()
        pedido_id = pedido.id
        app.config['ONESIGNAL_APP_ID'] = 'app-id-test'
        app.config['ONESIGNAL_REST_API_KEY'] = 'rest-key-test'
        app.config['PUBLIC_STORE_URL'] = 'https://leyly.example'

    with app.test_client() as client:
        resposta_login = client.post('/api/login', json={
            'nome': 'Cliente Recuperação',
            'whatsapp': '81999999999',
        })
        resposta_assinatura = client.post(
            '/api/onesignal/subscription',
            json={'subscription_id': 'subscription-id-test'},
        )

    assert resposta_login.status_code == 200
    assert resposta_login.get_json()['sucesso'] is True
    assert resposta_assinatura.status_code == 200
    assert resposta_assinatura.get_json()['sucesso'] is True
    with app.app_context():
        db.session.expire_all()
        usuario = db.session.get(Usuario, usuario_id)
        pedido = db.session.get(Pedido, pedido_id)
        assert usuario.onesignal_subscription_id == 'subscription-id-test'
        resposta_onesignal = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'id': 'notificacao-teste'},
        )
        with patch('app.routes.requests.post', return_value=resposta_onesignal) as enviar:
            resultado = enviar_notificacao_carrinho(usuario, pedido)
        assert resultado['id'] == 'notificacao-teste'
        payload = enviar.call_args.kwargs['json']
        assert payload['include_subscription_ids'] == ['subscription-id-test']
        assert payload['data']['pedido_id'] == pedido_id
