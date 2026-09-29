import json
import os
from datetime import datetime
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Pedido, Produto, Usuario


def _criar_app_e_usuario(email='teste@leyly.com', senha='123456'):
    os.environ.pop('MERCADO_PAGO_ACCESS_TOKEN', None)
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.drop_all()
        db.create_all()

        usuario = Usuario(nome='Teste', email=email, senha=generate_password_hash(senha), whatsapp='81999999999')
        db.session.add(usuario)
        db.session.flush()

        produto = Produto(
            codigo='REF-TESTE',
            nome='Produto teste',
            preco=100.0,
            etiqueta='TESTE',
            imagem_url='img/teste.jpg',
            estoque_p=10,
            estoque_m=10,
            estoque_g=10,
            estoque_gg=10,
        )
        db.session.add(produto)
        db.session.flush()

        pedido = Pedido(
            usuario_id=usuario.id,
            status='ABERTO',
            itens=json.dumps([
                {
                    'id': produto.id,
                    'nome': produto.nome,
                    'tamanho': 'P',
                    'preco': 100.0,
                    'quantidade': 4,
                    'imagem': produto.imagem_url,
                }
            ]),
            valor_total=400.0,
            frete_tipo='PAC',
            endereco='Rua Teste, 123',
            data_atualizacao=datetime.utcnow(),
        )
        db.session.add(pedido)
        nome_usuario = usuario.nome
        whatsapp_usuario = usuario.whatsapp
        db.session.commit()

        return app, nome_usuario, whatsapp_usuario


def test_checkout_retorna_url_de_pagamento_quando_token_existe():
    app, nome, whatsapp = _criar_app_e_usuario()

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        os.environ['MERCADO_PAGO_ACCESS_TOKEN'] = 'TEST-TOKEN'

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {
                'init_point': 'https://www.mercadopago.com.br/checkout/live',
                'sandbox_init_point': 'https://sandbox.mercadopago.com.br/checkout/test',
            }

            response = client.post('/checkout-infinitepay', json={'frete': 0})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is True
        assert dados['url_pagamento'] == 'https://sandbox.mercadopago.com.br/checkout/test'


def test_checkout_retorna_erro_claro_quando_token_nao_esta_configurado():
    app, nome, whatsapp = _criar_app_e_usuario(email='semtoken@leyly.com')

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        os.environ.pop('MERCADO_PAGO_ACCESS_TOKEN', None)

        response = client.post('/checkout-infinitepay', json={'frete': 0})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is False
        assert 'token' in dados['mensagem'].lower()


def test_checkout_com_token_de_producao_usa_init_point():
    app, nome, whatsapp = _criar_app_e_usuario(email='producao@leyly.com')

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.status_code == 200
        os.environ['MERCADO_PAGO_ACCESS_TOKEN'] = 'APP_USR-token-producao'

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {
                'init_point': 'https://www.mercadopago.com.br/checkout/live',
                'sandbox_init_point': 'https://sandbox.mercadopago.com.br/checkout/test',
            }
            response = client.post('/checkout-infinitepay', json={'frete': 0})

    assert response.get_json()['url_pagamento'] == 'https://www.mercadopago.com.br/checkout/live'


def test_checkout_nao_envia_email_interno_sintetico_ao_mercado_pago():
    email_interno = 'whatsapp+5581999999999@clientes.leyly.local'
    app, nome, whatsapp = _criar_app_e_usuario(email=email_interno)

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'nome': nome, 'whatsapp': whatsapp})
        assert login_response.get_json()['sucesso'] is True
        os.environ['MERCADO_PAGO_ACCESS_TOKEN'] = 'APP_USR-token-producao'

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {
                'init_point': 'https://www.mercadopago.com.br/checkout/live',
            }
            response = client.post('/checkout-infinitepay', json={'frete': 0})

    assert response.get_json()['sucesso'] is True
    assert mock_post.call_args.kwargs['json']['payer'] == {'name': nome}


def test_cadastro_login_nome_whatsapp_e_carrossel_principal():
    app, _, _ = _criar_app_e_usuario()

    with app.test_client() as client:
        cadastro = client.post('/api/cadastro', json={
            'nome': '  Maria da Silva  ',
            'whatsapp': '+55 (81) 98888-7777',
        })
        assert cadastro.get_json()['sucesso'] is True

        with client.session_transaction() as sessao:
            sessao.clear()

        login = client.post('/api/login', json={
            'nome': 'maria da silva',
            'whatsapp': '5581988887777',
        })
        assert login.get_json()['sucesso'] is True

        pagina = client.get('/').get_data(as_text=True)
        assert pagina.count('class="hero-slide"') + pagina.count('class="hero-slide is-active"') == 3
        assert 'id="loginNome"' in pagina
        assert 'id="loginWhatsapp"' in pagina
        assert 'id="loginEmail"' not in pagina
        assert 'id="cadEmail"' not in pagina
