import os
from PIL import Image, ImageOps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, current_app
from app.models import Produto, ProdutoImagem, Usuario, Pedido, Admin, Visita, ImagemSite
from app import db
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_
import requests
import json
from datetime import datetime, timedelta

main_bp = Blueprint('main', __name__)

@main_bp.app_context_processor
def fornecer_variantes_imagem():
    def imagem_variacao(caminho, variante):
        base, extensao = os.path.splitext(caminho)
        if extensao.lower() == '.gif':
            return caminho
        return f'{base}.{variante}.webp'

    return {'imagem_variacao': imagem_variacao}

# ==========================================
# GARI DE ESTOQUE (LIMPADOR AUTOMÁTICO)
# ==========================================
def limpar_carrinhos_abandonados():
    limite = datetime.utcnow() - timedelta(minutes=30)
    expirados = Pedido.query.filter(Pedido.status.in_(['ABERTO', 'PAGAMENTO']), Pedido.data_atualizacao < limite).all()
    
    for p in expirados:
        if p.itens and p.itens != '[]':
            itens = json.loads(p.itens)
            for item in itens:
                prod = Produto.query.get(item['id'])
                if prod:
                    atualizar_estoque_variante(prod, item.get('cor'), item['tamanho'], item['quantidade'])
        
        p.status = 'ABANDONADO'
        
    if expirados:
        db.session.commit()

def salvar_imagens_produto(produto, arquivos):
    arquivos_validos = [arquivo for arquivo in arquivos if arquivo and arquivo.filename]
    if not arquivos_validos:
        return

    ordem = max((imagem.ordem for imagem in produto.imagens), default=-1) + 1
    for arquivo in arquivos_validos:
        filename = secure_filename(arquivo.filename)
        if not filename:
            continue
        nome_unico = f'{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}_{filename}'
        save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], nome_unico)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        salvar_imagem_otimizada(arquivo, save_path, os.path.splitext(filename)[1].lower())
        caminho = f'uploads/{nome_unico}'
        if not produto.imagem_url or produto.imagem_url == 'img/default.jpg':
            produto.imagem_url = caminho
        else:
            db.session.add(ProdutoImagem(produto=produto, imagem_url=caminho, ordem=ordem))
            ordem += 1

def salvar_arquivo_imagem(arquivo):
    filename = secure_filename(arquivo.filename)
    extensao = os.path.splitext(filename)[1].lower()
    if not filename or extensao not in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}:
        raise ValueError('Selecione uma imagem JPG, PNG, WEBP ou GIF.')
    nome_unico = f'{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}_{filename}'
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], nome_unico)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    salvar_imagem_otimizada(arquivo, save_path, extensao)
    return f'uploads/{nome_unico}'

def salvar_imagem_otimizada(arquivo, save_path, extensao):
    if extensao == '.gif':
        arquivo.save(save_path)
        return

    with Image.open(arquivo.stream) as imagem:
        imagem = ImageOps.exif_transpose(imagem)
        if extensao in {'.jpg', '.jpeg'}:
            imagem.convert('RGB').save(save_path, 'JPEG', quality=88, optimize=True, progressive=True)
        elif extensao == '.png':
            imagem.save(save_path, 'PNG', optimize=True)
        elif extensao == '.webp':
            imagem.save(save_path, 'WEBP', quality=88, method=6)

    gerar_variantes_imagem(save_path)

def gerar_variantes_imagem(caminho):
    with Image.open(caminho) as origem:
        imagem = ImageOps.exif_transpose(origem)
        modo = 'RGBA' if 'A' in imagem.getbands() or 'transparency' in imagem.info else 'RGB'
        imagem = imagem.convert(modo)

        galeria = imagem.copy()
        galeria.thumbnail((960, 960), Image.Resampling.LANCZOS)
        galeria.save(f'{os.path.splitext(caminho)[0]}.gallery.webp', 'WEBP', quality=82, method=6)

        miniatura = imagem.copy()
        miniatura.thumbnail((180, 220), Image.Resampling.LANCZOS)
        miniatura.save(f'{os.path.splitext(caminho)[0]}.thumb.webp', 'WEBP', quality=72, method=5)

IMAGENS_SITE_PADRAO = {
    'banner_hero': ('Banner principal', 'img/banner_hero1.jpeg'),
    'banner_promise': ('Banner da seção de qualidade', 'img/banner_macaquinho.jpeg'),
    'banner_macaquinho': ('Banner de macaquinhos', 'img/banner_macaquinho.jpeg'),
    'banner_lounge': ('Banner da linha casual', 'img/banner_lounge.jpeg'),
    'categoria_conjuntos': ('Categoria conjuntos', 'img/cat_conjuntos.jpeg'),
    'categoria_leggings': ('Categoria leggings', 'img/cat_leggings.jpeg'),
    'categoria_casacos': ('Categoria casacos', 'img/cat_casacos.jpeg'),
    'categoria_tops': ('Categoria tops', 'img/cat_tops.jpeg'),
}

def garantir_imagens_site():
    alterado = False
    for chave, (nome, imagem_url) in IMAGENS_SITE_PADRAO.items():
        if not ImagemSite.query.filter_by(chave=chave).first():
            db.session.add(ImagemSite(chave=chave, nome=nome, imagem_url=imagem_url))
            alterado = True
    if alterado:
        db.session.commit()

def preco_tamanho(produto, tamanho):
    return getattr(produto, f'preco_{tamanho.lower()}', None) or produto.preco

def grade_do_produto(produto):
    return produto.grade_config

def variantes_do_produto(produto):
    return produto.variantes_config

def atualizar_estoque_variante(produto, cor, nome_tamanho, delta):
    variantes = variantes_do_produto(produto)
    for variante in variantes:
        mesma_cor = (variante.get('cor') or '').casefold() == (cor or '').casefold()
        if mesma_cor:
            for tamanho in variante.get('tamanhos', []):
                if tamanho['nome'].casefold() == str(nome_tamanho).casefold():
                    tamanho['estoque'] = max(0, int(tamanho.get('estoque', 0)) + delta)
                    produto.variantes = json.dumps(variantes, ensure_ascii=False)
                    return tamanho['estoque']
    return None

def atualizar_estoque_grade(produto, nome_tamanho, delta):
    grade = grade_do_produto(produto)
    for tamanho in grade:
        if tamanho['nome'].casefold() == str(nome_tamanho).casefold():
            tamanho['estoque'] = max(0, int(tamanho.get('estoque', 0)) + delta)
            produto.grade = json.dumps(grade, ensure_ascii=False)
            return tamanho['estoque']
    return None

def ler_precos_formulario(form, prefixo=''):
    precos = {}
    for tamanho in ('p', 'm', 'g', 'gg'):
        valor = form.get(f'{prefixo}preco_{tamanho}')
        precos[tamanho] = float(valor) if valor not in (None, '') else None
    return precos

# ==========================================
# ROTAS DA LOJA E AUTENTICAÇÃO
# ==========================================
@main_bp.route('/')
def index():
    limpar_carrinhos_abandonados()
    
    nova_visita = Visita(ip=request.remote_addr)
    db.session.add(nova_visita)
    db.session.commit()
    
    email_admin = current_app.config.get('ADMIN_EMAIL')
    senha_admin = current_app.config.get('ADMIN_PASSWORD')
    if Admin.query.count() == 0 and email_admin and senha_admin:
        hashed_admin = generate_password_hash(senha_admin, method='pbkdf2:sha256')
        db.session.add(Admin(email=email_admin, senha=hashed_admin))
        db.session.commit()

    garantir_imagens_site()
    imagens_site = {imagem.chave: imagem.imagem_url for imagem in ImagemSite.query.all()}

    page = request.args.get('page', 1, type=int)
    produtos_paginados = Produto.query.paginate(page=page, per_page=16, error_out=False)

    return render_template('index.html', 
                           produtos=produtos_paginados, 
                           imagens_site=imagens_site,
                           usuario_logado=current_user.is_authenticated, 
                           nome_usuario=current_user.nome if current_user.is_authenticated else "")

@main_bp.route('/api/cadastro', methods=['POST'])
def api_cadastro():
    dados = request.get_json()
    if Usuario.query.filter_by(email=dados.get('email')).first():
        return jsonify({"sucesso": False, "mensagem": "Este e-mail já está cadastrado."})

    novo_usuario = Usuario(nome=dados.get('nome'), email=dados.get('email'), senha=generate_password_hash(dados.get('senha'), method='pbkdf2:sha256'), whatsapp=dados.get('whatsapp'))
    db.session.add(novo_usuario)
    db.session.commit()
    login_user(novo_usuario)
    return jsonify({"sucesso": True, "mensagem": "Cadastro realizado com sucesso!"})

@main_bp.route('/api/login', methods=['POST'])
def api_login():
    dados = request.get_json()
    usuario = Usuario.query.filter_by(email=dados.get('email')).first()
    if usuario and check_password_hash(usuario.senha, dados.get('senha')):
        login_user(usuario)
        return jsonify({"sucesso": True, "nome": usuario.nome})
    return jsonify({"sucesso": False, "mensagem": "E-mail ou senha incorretos."})

@main_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

# ==========================================
# ROTAS DO PAINEL ADMIN
# ==========================================
@main_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logado'): return redirect(url_for('main.admin_dashboard'))
    erro = None
    if request.method == 'POST':
        admin = Admin.query.filter_by(email=request.form.get('email')).first()
        if admin and check_password_hash(admin.senha, request.form.get('senha')):
            session['admin_logado'] = True
            return redirect(url_for('main.admin_dashboard'))
        erro = "Credenciais administrativas inválidas."
    return render_template('admin_login.html', erro=erro)

@main_bp.route('/admin/logout')
def admin_logout():
    session.pop('admin_logado', None)
    return redirect(url_for('main.admin_login'))

@main_bp.route('/admin')
def admin_dashboard():
    if not session.get('admin_logado'): return redirect(url_for('main.admin_login'))
    return render_template('admin.html')

@main_bp.route('/api/admin/pedidos')
def api_admin_pedidos():
    if not session.get('admin_logado'): return jsonify([])
    limpar_carrinhos_abandonados()
    
    pedidos = Pedido.query.all()
    resultado = []
    for p in pedidos:
        itens_enriquecidos = []
        if p.itens and p.itens != '[]':
            for item in json.loads(p.itens):
                prod = Produto.query.get(item['id'])
                item['codigo'] = prod.codigo if prod else '-'
                itens_enriquecidos.append(item)

        resultado.append({
            "id": p.id, "cliente": p.usuario.nome, "whatsapp": p.usuario.whatsapp, "endereco": p.endereco, "frete_tipo": p.frete_tipo,
            "status": p.status, "total": p.valor_total, "itens": itens_enriquecidos, "atualizado": p.data_atualizacao.strftime('%d/%m %H:%M')
        })
    return jsonify(resultado)

@main_bp.route('/api/admin/pedidos/atualizar-status', methods=['POST'])
def api_admin_atualizar_status_pedido():
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    dados = request.get_json()
    pedido = Pedido.query.get(dados.get('id'))
    if pedido:
        pedido.status = dados.get('status')
        pedido.data_atualizacao = datetime.utcnow()
        db.session.commit()
        return jsonify({"sucesso": True})
    return jsonify({"sucesso": False})

@main_bp.route('/api/admin/produtos', methods=['GET'])
def api_admin_produtos():
    if not session.get('admin_logado'): return jsonify([])
    produtos = Produto.query.all()
    # Adicionado preco e imagem_url para a função de Edição no Frontend
    return jsonify([{
        "id": p.id, "codigo": p.codigo, "nome": p.nome, "preco": p.preco,
        "precos": {tamanho: preco_tamanho(p, tamanho) for tamanho in ('P', 'M', 'G', 'GG')}, "grade": grade_do_produto(p), "cores": p.cores_config, "variantes": variantes_do_produto(p), "imagem_url": p.imagem_url,
        "imagens": [imagem.imagem_url for imagem in p.imagens],
        "p": p.estoque_p, "m": p.estoque_m, "g": p.estoque_g, "gg": p.estoque_gg
    } for p in produtos])

@main_bp.route('/api/admin/imagens-site')
def api_admin_imagens_site():
    if not session.get('admin_logado'):
        return jsonify([])
    garantir_imagens_site()
    return jsonify([{'chave': imagem.chave, 'nome': imagem.nome, 'imagem_url': imagem.imagem_url} for imagem in ImagemSite.query.order_by(ImagemSite.id).all()])

@main_bp.route('/api/admin/imagens-site/<chave>', methods=['POST'])
def api_admin_atualizar_imagem_site(chave):
    if not session.get('admin_logado'):
        return jsonify({'sucesso': False, 'mensagem': 'Não autorizado.'}), 401
    imagem = ImagemSite.query.filter_by(chave=chave).first()
    arquivo = request.files.get('imagem')
    if not imagem or not arquivo or not arquivo.filename:
        return jsonify({'sucesso': False, 'mensagem': 'Selecione uma imagem.'})
    try:
        imagem.imagem_url = salvar_arquivo_imagem(arquivo)
        db.session.commit()
        return jsonify({'sucesso': True, 'imagem_url': imagem.imagem_url})
    except (ValueError, OSError) as erro:
        db.session.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(erro)})

@main_bp.route('/api/admin/produtos/atualizar', methods=['POST'])
def api_admin_atualizar_estoque():
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    dados = request.get_json()
    prod = Produto.query.get(dados.get('id'))
    if prod:
        prod.estoque_p = int(dados.get('p') or 0); prod.estoque_m = int(dados.get('m') or 0); prod.estoque_g = int(dados.get('g') or 0); prod.estoque_gg = int(dados.get('gg') or 0)
        db.session.commit()
        return jsonify({"sucesso": True})
    return jsonify({"sucesso": False})

@main_bp.route('/api/admin/produtos/cadastrar', methods=['POST'])
def api_admin_cadastrar_produto():
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    try:
        codigo = request.form.get('codigo', '').strip()
        nome = request.form.get('nome', '').strip()
        arquivos = [arquivo for arquivo in request.files.getlist('imagens') if arquivo and arquivo.filename]
        precos = ler_precos_formulario(request.form)
        try:
            grade_personalizada = json.loads(request.form.get('grade', '[]'))
        except json.JSONDecodeError:
            grade_personalizada = []
        try:
            cores_personalizadas = json.loads(request.form.get('cores', '[]'))
        except json.JSONDecodeError:
            cores_personalizadas = []
        try:
            variantes_personalizadas = json.loads(request.form.get('variantes', '[]'))
        except json.JSONDecodeError:
            variantes_personalizadas = []
        preco_unico = request.form.get('preco')
        quantidades = [int(request.form.get(tamanho) or 0) for tamanho in ('p', 'm', 'g', 'gg')]
        if not codigo or not nome or not arquivos or not variantes_personalizadas:
            return jsonify({"sucesso": False, "mensagem": "Código, nome e pelo menos uma foto são obrigatórios."})
        precos_grade = [float(tamanho.get('preco')) for variante in variantes_personalizadas for tamanho in variante.get('tamanhos', []) if tamanho.get('preco') not in (None, '')]
        if not preco_unico and len(precos_grade) != len(grade_personalizada):
            return jsonify({"sucesso": False, "mensagem": "Informe um preço único ou o preço de cada tamanho."})
        preco_base = float(preco_unico or precos_grade[0])
        if preco_unico:
            precos = {'p': None, 'm': None, 'g': None, 'gg': None}
        variantes_normalizadas = []
        for variante in variantes_personalizadas:
            tamanhos = [{'nome': str(t.get('nome', '')).strip(), 'estoque': max(0, int(t.get('estoque', 0))), 'preco': float(t.get('preco') or preco_base)} for t in variante.get('tamanhos', []) if str(t.get('nome', '')).strip()]
            if tamanhos and variante.get('cor'):
                variantes_normalizadas.append({'cor': variante['cor'], 'tamanhos': tamanhos})
        if not variantes_normalizadas:
            return jsonify({"sucesso": False, "mensagem": "Adicione pelo menos uma cor e um tamanho válido."})
        cores_normalizadas = [cor for cor in cores_personalizadas if isinstance(cor, str) and cor.startswith('#') and len(cor) == 7]
        grade_normalizada = variantes_normalizadas[0]['tamanhos']
        novo_produto = Produto(codigo=codigo, nome=nome, preco=preco_base, preco_p=precos['p'], preco_m=precos['m'], preco_g=precos['g'], preco_gg=precos['gg'], grade=json.dumps(grade_normalizada, ensure_ascii=False), cores=json.dumps(cores_normalizadas), variantes=json.dumps(variantes_normalizadas, ensure_ascii=False), etiqueta='NOVO', imagem_url='img/default.jpg', estoque_p=quantidades[0], estoque_m=quantidades[1], estoque_g=quantidades[2], estoque_gg=quantidades[3])
        db.session.add(novo_produto)
        salvar_imagens_produto(novo_produto, arquivos)
        db.session.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/admin/produtos/editar/<int:id>', methods=['POST'])
def api_admin_editar_produto(id):
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    try:
        prod = Produto.query.get(id)
        if not prod: return jsonify({"sucesso": False, "mensagem": "Produto não encontrado."})

        prod.codigo = request.form.get('codigo', prod.codigo)
        prod.nome = request.form.get('nome', prod.nome)
        if request.form.get('preco'):
            prod.preco = float(request.form.get('preco'))
        precos = ler_precos_formulario(request.form)
        for tamanho, valor in precos.items():
            setattr(prod, f'preco_{tamanho}', valor)
        if request.form.get('grade'):
            prod.grade = request.form.get('grade')
        if request.form.get('cores') is not None:
            prod.cores = json.dumps([cor for cor in json.loads(request.form.get('cores', '[]')) if isinstance(cor, str) and cor.startswith('#') and len(cor) == 7])
        if request.form.get('variantes'):
            prod.variantes = request.form.get('variantes')
            prod.grade = json.dumps(json.loads(request.form.get('variantes'))[0].get('tamanhos', []), ensure_ascii=False)

        capa = request.files.get('capa')
        if capa and capa.filename:
            prod.imagem_url = salvar_arquivo_imagem(capa)
            
        salvar_imagens_produto(prod, request.files.getlist('imagens'))

        prod.estoque_p = int(request.form.get('p', prod.estoque_p))
        prod.estoque_m = int(request.form.get('m', prod.estoque_m))
        prod.estoque_g = int(request.form.get('g', prod.estoque_g))
        prod.estoque_gg = int(request.form.get('gg', prod.estoque_gg))

        db.session.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/admin/produtos/excluir/<int:id>', methods=['POST'])
def api_admin_excluir_produto(id):
    if not session.get('admin_logado'): return jsonify({"sucesso": False})
    try:
        prod = Produto.query.get(id)
        if prod:
            db.session.delete(prod)
            db.session.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/admin/dashboard')
def api_admin_dashboard():
    if not session.get('admin_logado'): return jsonify({})
    limpar_carrinhos_abandonados()
    
    pedidos = Pedido.query.all()
    fat = 0; qtd_vendas = 0; pecas = 0; abandonos = 0; abertos = 0; fretes = {}; valor_perdido = 0
    produtos_vendidos = {}
    clientes_compras = {}

    for p in pedidos:
        if p.status in ['PAGO', 'SEPARACAO', 'CONCLUIDO']:
            fat += p.valor_total
            qtd_vendas += 1
            nome_cliente = p.usuario.nome if p.usuario else 'Cliente não identificado'
            clientes_compras[nome_cliente] = clientes_compras.get(nome_cliente, 0) + 1
            if p.itens and p.itens != '[]':
                for item in json.loads(p.itens):
                    pecas += item['quantidade']
                    nome_base = item['nome']
                    produtos_vendidos[nome_base] = produtos_vendidos.get(nome_base, 0) + item['quantidade']
            tipo_f = p.frete_tipo or 'Não Selecionado'
            fretes[tipo_f] = fretes.get(tipo_f, 0) + 1
        elif p.status == 'ABANDONADO': 
            abandonos += 1
            valor_perdido += p.valor_total
        elif p.status in ['ABERTO', 'PAGAMENTO']: 
            abertos += 1
            
    total_iniciados = abandonos + abertos + qtd_vendas
    taxa_abandono = (abandonos / total_iniciados * 100) if total_iniciados > 0 else 0
    ticket_medio = (fat / qtd_vendas) if qtd_vendas > 0 else 0
    top_produtos = sorted(produtos_vendidos.items(), key=lambda x: x[1], reverse=True)[:5]
    top_clientes = sorted(clientes_compras.items(), key=lambda x: x[1], reverse=True)[:5]
    
    prod_risco = Produto.query.filter(or_(Produto.estoque_p <= 5, Produto.estoque_m <= 5, Produto.estoque_g <= 5, Produto.estoque_gg <= 5)).all()
    risco_ruptura = [{"nome": pr.nome, "estoque": f"P:{pr.estoque_p} M:{pr.estoque_m} G:{pr.estoque_g} GG:{pr.estoque_gg}"} for pr in prod_risco]

    return jsonify({
        "kpis": {"faturamento": fat, "ticket_medio": ticket_medio, "pecas_vendidas": pecas, "taxa_abandono": taxa_abandono, "valor_perdido": valor_perdido},
        "graficos": {"produtos_labels": [x[0][:15]+"..." for x in top_produtos], "produtos_data": [x[1] for x in top_produtos], "clientes_labels": [x[0][:18]+"..." for x in top_clientes], "clientes_data": [x[1] for x in top_clientes], "fretes_labels": list(fretes.keys()), "fretes_data": list(fretes.values())},
        "risco_ruptura": risco_ruptura
    })

@main_bp.route('/api/admin/relatorios')
def api_admin_relatorios():
    if not session.get('admin_logado'): return jsonify({})
    hoje = datetime.utcnow().date()
    datas_labels = [(hoje - timedelta(days=i)).strftime('%d/%m') for i in range(6, -1, -1)]
    
    acessos_data = [0] * 7
    visitas = Visita.query.filter(Visita.data_visita >= datetime.utcnow() - timedelta(days=7)).all()
    for v in visitas:
        dia_str = v.data_visita.strftime('%d/%m')
        if dia_str in datas_labels: acessos_data[datas_labels.index(dia_str)] += 1
            
    vendas_data = [0] * 7
    pedidos = Pedido.query.filter(Pedido.status.in_(['PAGO', 'SEPARACAO', 'CONCLUIDO']), Pedido.data_atualizacao >= datetime.utcnow() - timedelta(days=7)).all()
    for p in pedidos:
        dia_str = p.data_atualizacao.strftime('%d/%m')
        if dia_str in datas_labels: vendas_data[datas_labels.index(dia_str)] += 1

    return jsonify({"labels": datas_labels, "acessos": acessos_data, "vendas": vendas_data})

@main_bp.route('/api/admin/marketing')
def api_admin_marketing():
    if not session.get('admin_logado'): return jsonify({})
    hoje = datetime.utcnow()
    limite_30d = hoje - timedelta(days=30)
    
    visitas = Visita.query.filter(Visita.data_visita >= limite_30d).count()
    pedidos_iniciados = Pedido.query.filter(Pedido.data_atualizacao >= limite_30d).count()
    pedidos_pagos = Pedido.query.filter(Pedido.status.in_(['PAGO', 'SEPARACAO', 'CONCLUIDO']), Pedido.data_atualizacao >= limite_30d).count()
    taxa_conversao = (pedidos_pagos / visitas * 100) if visitas > 0 else 0
    
    abandonados_db = Pedido.query.filter(Pedido.status == 'ABANDONADO', Pedido.data_atualizacao >= limite_30d).all()
    prod_abandonados = {}
    for p in abandonados_db:
        if p.itens and p.itens != '[]':
            for item in json.loads(p.itens):
                nome = item['nome']
                prod_abandonados[nome] = prod_abandonados.get(nome, 0) + item['quantidade']
    
    top_abandonados = sorted(prod_abandonados.items(), key=lambda x: x[1], reverse=True)[:5]
    usuarios_marketing = Usuario.query.order_by(Usuario.nome.asc()).all()
    return jsonify({
        "funil": {"visitas": visitas, "iniciados": pedidos_iniciados, "pagos": pedidos_pagos},
        "conversao": taxa_conversao,
        "top_abandonados": [{"nome": x[0], "qtd": x[1]} for x in top_abandonados],
        "usuarios": [{"id": u.id, "nome": u.nome, "whatsapp": u.whatsapp or "Não informado", "email": u.email} for u in usuarios_marketing]
    })

@main_bp.route('/api/admin/usuarios')
def api_admin_usuarios():
    if not session.get('admin_logado'): return jsonify([])
    usuarios = Usuario.query.order_by(Usuario.nome.asc()).all()
    return jsonify([{
        "id": u.id,
        "nome": u.nome,
        "email": u.email,
        "whatsapp": u.whatsapp or "Não informado",
        "especial": u.cliente_especial,
        "pedidos": sum(1 for pedido in u.pedidos if pedido.status in ['PAGO', 'SEPARACAO', 'CONCLUIDO'])
    } for u in usuarios])

@main_bp.route('/api/admin/usuarios/<int:usuario_id>/especial', methods=['POST'])
def api_admin_marcar_usuario_especial(usuario_id):
    if not session.get('admin_logado'):
        return jsonify({"sucesso": False, "mensagem": "Não autorizado"}), 403
    usuario = Usuario.query.get(usuario_id)
    if not usuario:
        return jsonify({"sucesso": False, "mensagem": "Usuário não encontrado"}), 404
    dados = request.get_json(silent=True) or {}
    usuario.cliente_especial = bool(dados.get('especial'))
    db.session.commit()
    return jsonify({"sucesso": True, "especial": usuario.cliente_especial})

@main_bp.route('/api/admin/gerar-etiqueta/<int:pedido_id>')
def api_gerar_etiqueta(pedido_id):
    if not session.get('admin_logado'): return jsonify({"sucesso": False, "mensagem": "Não autorizado"})
    pedido = Pedido.query.get(pedido_id)
    if not pedido: return jsonify({"sucesso": False, "mensagem": "Pedido não encontrado"})
    if pedido.status not in ['PAGO', 'SEPARACAO', 'CONCLUIDO']: return jsonify({"sucesso": False, "mensagem": "Etiqueta disponível apenas para pedidos confirmados."})
    url_pdf_gerado = f"https://sua-api-de-frete.com/etiquetas/print_pedido_{pedido.id}.pdf"
    return jsonify({"sucesso": True, "url_etiqueta": url_pdf_gerado})

# ==========================================
# CHECKOUT E VALIDAÇÃO DE ESTOQUE
# ==========================================
@main_bp.route('/api/carrinho/sync', methods=['POST'])
@login_required
def sync_carrinho():
    limpar_carrinhos_abandonados()
    dados = request.get_json()
    novo_carrinho = dados.get('carrinho', [])
    valor_frete = float(dados.get('frete', 0))
    frete_tipo = dados.get('frete_tipo', 'Não selecionado')
    endereco_envio = dados.get('endereco', '')

    pedido = Pedido.query.filter_by(usuario_id=current_user.id).filter(Pedido.status.in_(['ABERTO', 'PAGAMENTO'])).first()

    if pedido and pedido.itens != '[]':
        itens_antigos = json.loads(pedido.itens)
        for item in itens_antigos:
            prod = Produto.query.get(item['id'])
            if prod:
                atualizar_estoque_variante(prod, item.get('cor'), item['tamanho'], item['quantidade'])
    
    if novo_carrinho:
        for item in novo_carrinho:
            prod = Produto.query.get(item['id'])
            if not prod:
                db.session.rollback()
                return jsonify({"sucesso": False, "mensagem": f"O produto '{item['nome']}' foi removido do catálogo."})
            
            variante_configurada = next((variante for variante in variantes_do_produto(prod) if (variante.get('cor') or '').casefold() == (item.get('cor') or '').casefold()), None)
            tamanho_configurado = next((tamanho for tamanho in (variante_configurada or {}).get('tamanhos', []) if tamanho['nome'].casefold() == str(item['tamanho']).casefold()), None)
            estoque_disp = int(tamanho_configurado.get('estoque', 0)) if tamanho_configurado else 0
            
            if int(item['quantidade']) > estoque_disp:
                db.session.rollback()
                return jsonify({
                    "sucesso": False, 
                    "mensagem": f"O item '{item['nome']}' (Tam: {item['tamanho'].upper()}) esgotou ou não possui a quantidade desejada. Restam {estoque_disp} unidades no momento."
                })

    if not novo_carrinho and pedido:
        pedido.itens = '[]'
        pedido.valor_total = 0
        db.session.commit()
        return jsonify({"sucesso": True})

    if not pedido and novo_carrinho:
        pedido = Pedido(usuario_id=current_user.id, status='ABERTO')
        db.session.add(pedido)

    if novo_carrinho:
        carrinho_ajustado = []
        for item in novo_carrinho:
            prod = Produto.query.get(item['id'])
            estoque_disp = atualizar_estoque_variante(prod, item.get('cor'), item['tamanho'], -int(item['quantidade']))
            carrinho_ajustado.append(item)
                    
        pedido.itens = json.dumps(carrinho_ajustado)
        pedido.valor_total = sum(float(i['preco']) * int(i['quantidade']) for i in carrinho_ajustado) + valor_frete
        pedido.frete_tipo = frete_tipo
        if endereco_envio: pedido.endereco = endereco_envio
        pedido.status = 'ABERTO'
        pedido.data_atualizacao = datetime.utcnow()
        db.session.commit()

    return jsonify({"sucesso": True})

@main_bp.route('/calcular-frete', methods=['POST'])
def calcular_frete():
    if not current_user.is_authenticated: return jsonify({"sucesso": False, "mensagem": "Faça login para calcular o frete."})
    data = request.get_json()
    cep_destino = data.get('cep', '').replace('-', '')
    carrinho = data.get('carrinho', [])
    if len(cep_destino) != 8: return jsonify({"sucesso": False, "mensagem": "CEP inválido"})
    
    res = requests.get(f"https://viacep.com.br/ws/{cep_destino}/json/")
    opcoes_frete = []
    if res.status_code == 200 and "erro" not in res.json():
        endereco_via_cep = f"{res.json().get('logradouro')}, {res.json().get('bairro')} - {res.json().get('localidade')}/{res.json().get('uf')} - CEP: {cep_destino}"
        pedido = Pedido.query.filter_by(usuario_id=current_user.id).filter(Pedido.status.in_(['ABERTO', 'PAGAMENTO'])).first()
        if pedido:
            pedido.endereco = endereco_via_cep
            db.session.commit()
            
        bp = 15.0 if res.json().get('uf') in ['PE', 'PB', 'AL', 'RN'] else 28.0
        opcoes_frete = [{"id": 1, "nome": "PAC", "transportadora": "Correios", "valor": bp, "prazo": "6 a 8 dias úteis"}, {"id": 2, "nome": "Sedex", "transportadora": "Correios", "valor": bp + 22.50, "prazo": "2 a 3 dias úteis"}, {"id": 3, "nome": ".Package", "transportadora": "Jadlog", "valor": bp - 2.10, "prazo": "5 a 7 dias úteis"}]
    opcoes_frete.append({"id": "excursao", "nome": "Envio por Excursão", "transportadora": "Excursão", "valor": 0.00, "prazo": "A combinar"})
    return jsonify({"sucesso": True, "opcoes": opcoes_frete})

@main_bp.route('/checkout-infinitepay', methods=['POST'])
@login_required
def checkout_pagamento():
    limpar_carrinhos_abandonados()
    pedido = Pedido.query.filter_by(usuario_id=current_user.id).filter(Pedido.status.in_(['ABERTO', 'PAGAMENTO'])).first()
    
    if not pedido or pedido.itens == '[]': 
        return jsonify({"sucesso": False, "mensagem": "Sua reserva expirou (30 minutos) e os itens voltaram ao estoque. Verifique sua sacola, pois algum produto pode ter esgotado."})

    itens_reservados = json.loads(pedido.itens)
    subtotal = sum(float(i['preco']) * int(i['quantidade']) for i in itens_reservados)
    if subtotal < 330.00: return jsonify({"sucesso": False, "mensagem": "Adicione mais produtos para finalizar o pedido."})

    dados = request.get_json(silent=True) or {}
    frete = float(dados.get('frete', 0) or 0)

    if current_user.cliente_especial:
        total = subtotal + frete
        resumo = [f"Olá! Sou {current_user.nome} e gostaria de finalizar este pedido:", ""]
        resumo.extend(f"{int(item['quantidade'])}x {item['nome']} - Tam. {item['tamanho']} - R$ {float(item['preco']) * int(item['quantidade']):.2f}" for item in itens_reservados)
        resumo.extend(["", f"Subtotal: R$ {subtotal:.2f}", f"Frete: R$ {frete:.2f}", f"Total: R$ {total:.2f}", f"Pedido de referência: #{pedido.id}"])
        pedido.status = 'PAGAMENTO'
        pedido.valor_total = total
        pedido.data_atualizacao = datetime.utcnow()
        db.session.commit()
        numero_loja = current_app.config.get('WHATSAPP_LOJA', '5581994597999')
        return jsonify({"sucesso": True, "url_whatsapp": f"https://wa.me/{numero_loja}?text={requests.utils.quote(chr(10).join(resumo))}"})

    access_token = os.environ.get('MERCADO_PAGO_ACCESS_TOKEN') or current_app.config.get('MERCADO_PAGO_ACCESS_TOKEN')
    if not access_token:
        return jsonify({"sucesso": False, "mensagem": "Mercado Pago não configurado: defina a variável MERCADO_PAGO_ACCESS_TOKEN antes de finalizar a venda."})

    pedido.status = 'PAGAMENTO'
    pedido.data_atualizacao = datetime.utcnow()
    db.session.commit()

    items_mp = [{"title": f"{i['nome']} (Tam:{i['tamanho']})", "quantity": int(i['quantidade']), "currency_id": "BRL", "unit_price": float(i['preco'])} for i in itens_reservados]
    if frete > 0: items_mp.append({"title": "Frete", "quantity": 1, "currency_id": "BRL", "unit_price": frete})

    payload_mp = {
        "items": items_mp,
        "external_reference": str(pedido.id),
        "payer": {"name": current_user.nome, "email": current_user.email},
        "back_urls": {"success": request.url_root, "failure": request.url_root, "pending": request.url_root},
        "notification_url": f"{request.url_root.rstrip('/')}/api/mercadopago/webhook",
        "auto_return": "approved"
    }

    try:
        r = requests.post(
            "https://api.mercadopago.com/checkout/preferences",
            json=payload_mp,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if r.status_code in (200, 201):
            init_point = r.json().get("init_point")
            if not init_point:
                return jsonify({"sucesso": False, "mensagem": "Mercado Pago respondeu sem URL de checkout. Verifique a configuração do token e das permissões do vendedor."})
            return jsonify({"sucesso": True, "url_pagamento": init_point})
        corpo = r.json() if r.content else {}
        mensagem = corpo.get('message') or corpo.get('error') or f"Erro do Mercado Pago ({r.status_code})"
        return jsonify({"sucesso": False, "mensagem": f"Erro MP: {mensagem}"})
    except requests.RequestException as e:
        return jsonify({"sucesso": False, "mensagem": f"Erro de conexão com o Mercado Pago: {str(e)}"})
    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": str(e)})

@main_bp.route('/api/mercadopago/webhook', methods=['POST', 'GET'])
def webhook_mercadopago():
    dados = request.get_json(silent=True) or {}
    payment_id = request.args.get('data.id') or request.args.get('id') or dados.get('data', {}).get('id')

    if payment_id:
        headers = {"Authorization": "Bearer APP_USR-4605924732795730-082514-374272a2de1d3b789462ba88224527e0-125327286"}
        res = requests.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers=headers)
        if res.status_code == 200:
            payment_info = res.json()
            status_mp = payment_info.get("status")
            pedido_id = payment_info.get("external_reference")

            if status_mp == "approved" and pedido_id:
                pedido = Pedido.query.get(int(pedido_id))
                if pedido and pedido.status in ['ABERTO', 'PAGAMENTO']:
                    pedido.status = 'PAGO'
                    pedido.data_atualizacao = datetime.utcnow()
                    db.session.commit()

    return jsonify({"status": "received"}), 200