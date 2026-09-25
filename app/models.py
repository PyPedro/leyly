from app import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import Boolean
import json

class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=True)
    nome = db.Column(db.String(100), nullable=False)
    preco = db.Column(db.Float, nullable=False)
    preco_p = db.Column(db.Float, nullable=True)
    preco_m = db.Column(db.Float, nullable=True)
    preco_g = db.Column(db.Float, nullable=True)
    preco_gg = db.Column(db.Float, nullable=True)
    grade = db.Column(db.Text, nullable=True)
    cores = db.Column(db.Text, nullable=True)
    variantes = db.Column(db.Text, nullable=True)
    etiqueta = db.Column(db.String(50), nullable=False)
    imagem_url = db.Column(db.String(200), nullable=False)
    
    estoque_p = db.Column(db.Integer, default=5, nullable=False)
    estoque_m = db.Column(db.Integer, default=10, nullable=False)
    estoque_g = db.Column(db.Integer, default=10, nullable=False)
    estoque_gg = db.Column(db.Integer, default=5, nullable=False)
    imagens = db.relationship('ProdutoImagem', backref='produto', cascade='all, delete-orphan', order_by='ProdutoImagem.ordem', lazy=True)

    @property
    def grade_config(self):
        if self.grade:
            try:
                return json.loads(self.grade)
            except (TypeError, json.JSONDecodeError):
                pass
        return [
            {'nome': tamanho, 'estoque': getattr(self, f'estoque_{tamanho.lower()}'), 'preco': getattr(self, f'preco_{tamanho.lower()}') or self.preco}
            for tamanho in ('P', 'M', 'G', 'GG')
        ]

    @property
    def cores_config(self):
        if not self.cores:
            return []
        try:
            return json.loads(self.cores)
        except (TypeError, json.JSONDecodeError):
            return []

    @property
    def variantes_config(self):
        if self.variantes:
            try:
                return json.loads(self.variantes)
            except (TypeError, json.JSONDecodeError):
                pass
        return [{'cor': None, 'tamanhos': self.grade_config}]

class ProdutoImagem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False, index=True)
    imagem_url = db.Column(db.String(200), nullable=False)
    ordem = db.Column(db.Integer, nullable=False, default=0)

class ImagemSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(80), unique=True, nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    imagem_url = db.Column(db.String(200), nullable=False)

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    whatsapp = db.Column(db.String(20), nullable=True)
    cliente_especial = db.Column(Boolean, default=False, nullable=False)

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    status = db.Column(db.String(50), default='ABERTO') 
    itens = db.Column(db.Text, default='[]')
    valor_total = db.Column(db.Float, default=0.0)
    frete_tipo = db.Column(db.String(100), default='Não selecionado')
    endereco = db.Column(db.String(255), nullable=True)
    data_atualizacao = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship('Usuario', backref=db.backref('pedidos', lazy=True))

class Visita(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_visita = db.Column(db.DateTime, default=datetime.utcnow)
    ip = db.Column(db.String(50), nullable=True)