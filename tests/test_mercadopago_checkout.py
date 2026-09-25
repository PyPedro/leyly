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
                    'quantidade': 1,
                    'imagem': produto.imagem_url,
                }
            ]),
            valor_total=100.0,
            frete_tipo='PAC',
            endereco='Rua Teste, 123',
            data_atualizacao=datetime.utcnow(),
        )
        db.session.add(pedido)
        db.session.commit()

        return app, usuario, pedido


def test_checkout_retorna_url_de_pagamento_quando_token_existe():
    app, usuario, _ = _criar_app_e_usuario()

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'email': usuario.email, 'senha': '123456'})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        os.environ['MERCADO_PAGO_ACCESS_TOKEN'] = 'TEST-TOKEN'

        with patch('app.routes.requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {'init_point': 'https://www.mercadopago.com.br/checkout/init'}

            response = client.post('/checkout-infinitepay', json={'frete': 0})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is True
        assert dados['url_pagamento'] == 'https://www.mercadopago.com.br/checkout/init'


def test_checkout_retorna_erro_claro_quando_token_nao_esta_configurado():
    app, usuario, _ = _criar_app_e_usuario(email='semtoken@leyly.com')

    with app.test_client() as client:
        login_response = client.post('/api/login', json={'email': usuario.email, 'senha': '123456'})
        assert login_response.status_code == 200
        assert login_response.get_json()['sucesso'] is True

        os.environ.pop('MERCADO_PAGO_ACCESS_TOKEN', None)

        response = client.post('/checkout-infinitepay', json={'frete': 0})

        assert response.status_code == 200
        dados = response.get_json()
        assert dados['sucesso'] is False
        assert 'token' in dados['mensagem'].lower()
