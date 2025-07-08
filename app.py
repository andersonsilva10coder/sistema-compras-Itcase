import os
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_ # Ferramenta para criar filtros complexos (E/OU)
from collections import defaultdict
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO ---
app = Flask(__name__)
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'compras.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- DEFINIÇÃO DAS TABELas (não muda) ---
class Fornecedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    solicitacoes = db.relationship('SolicitacaoCompra', backref='fornecedor', lazy=True)

class Segmento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    solicitacoes = db.relationship('SolicitacaoCompra', backref='segmento', lazy=True)

class SolicitacaoCompra(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_nome = db.Column(db.String(150), nullable=False)
    marca = db.Column(db.String(100))
    codigo = db.Column(db.String(50))
    quantidade = db.Column(db.Integer, nullable=False)
    observacao = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False, default='Aguardando Aprovação')
    data_solicitacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    data_execucao = db.Column(db.DateTime, nullable=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedor.id'), nullable=False)
    segmento_id = db.Column(db.Integer, db.ForeignKey('segmento.id'), nullable=False)

# --- FUNÇÃO DE SETUP DO BANCO (não muda) ---
def setup_database(app):
    with app.app_context():
        db.create_all()
        if Segmento.query.count() == 0:
            segmentos_iniciais = [
                'CARREGADORES', 'PELÍCULAS', 'CAPAS', 'CABOS', 'FONTES', 
                'OUTROS', 'POWERBANK', 'FONES', 'SMARTWATCH', 'LUMINÁRIAS', 
                'CAIXAS DE SOM', 'ADAPTADORES', 'SUPORTES', 'Desejos'
            ]
            for nome_segmento in segmentos_iniciais:
                db.session.add(Segmento(nome=nome_segmento))
            db.session.commit()

# --- PÁGINAS WEB (ROTAS) ---

@app.route('/')
def index():
    dez_dias_atras = datetime.utcnow() - timedelta(days=10)

    # **** CORREÇÃO AQUI ****
    # Usando and_() para agrupar as condições de 'Comprado'
    solicitacoes_visiveis = SolicitacaoCompra.query.filter(
        or_(
            SolicitacaoCompra.status.in_(['Aguardando Aprovação', 'Em Cotação']),
            and_(
                SolicitacaoCompra.status == 'Comprado', 
                SolicitacaoCompra.data_execucao >= dez_dias_atras
            )
        )
    ).order_by(SolicitacaoCompra.data_solicitacao.desc()).all()

    pedidos_por_fornecedor = defaultdict(list)
    for s in solicitacoes_visiveis:
        pedidos_por_fornecedor[s.fornecedor.nome].append(s)

    return render_template('index.html', pedidos_agrupados=pedidos_por_fornecedor)

@app.route('/historico')
def historico():
    dez_dias_atras = datetime.utcnow() - timedelta(days=10)

    # **** CORREÇÃO AQUI ****
    # Usando and_() para agrupar as condições de 'Comprado'
    solicitacoes_finalizadas = SolicitacaoCompra.query.filter(
        or_(
            SolicitacaoCompra.status == 'Cancelado',
            and_(
                SolicitacaoCompra.status == 'Comprado',
                SolicitacaoCompra.data_execucao < dez_dias_atras
            )
        )
    ).order_by(SolicitacaoCompra.data_execucao.desc().nulls_last(), SolicitacaoCompra.data_solicitacao.desc()).all()

    return render_template('historico.html', solicitacoes=solicitacoes_finalizadas)

# ... (as outras rotas /adicionar, /mudar_status, /baixar_relatorio não mudam) ...
@app.route('/adicionar', methods=['GET', 'POST'])
def adicionar():
    if request.method == 'POST':
        nome_fornecedor = request.form['fornecedor']
        segmento_id = request.form['segmento_id']
        produto_nome = request.form['produto_nome']
        marca = request.form['marca']
        codigo = request.form['codigo']
        quantidade = request.form['quantidade']
        observacao = request.form['observacao']
        fornecedor = Fornecedor.query.filter_by(nome=nome_fornecedor).first()
        if not fornecedor:
            fornecedor = Fornecedor(nome=nome_fornecedor)
            db.session.add(fornecedor)
            db.session.commit()
        nova_solicitacao = SolicitacaoCompra(
            fornecedor_id=fornecedor.id,
            segmento_id=segmento_id,
            produto_nome=produto_nome,
            marca=marca,
            codigo=codigo,
            quantidade=quantidade,
            observacao=observacao
        )
        db.session.add(nova_solicitacao)
        db.session.commit()
        return redirect(url_for('index'))
    segmentos = Segmento.query.all()
    return render_template('adicionar.html', segmentos=segmentos)

@app.route('/mudar_status/<int:solicitacao_id>', methods=['POST'])
def mudar_status(solicitacao_id):
    solicitacao = SolicitacaoCompra.query.get_or_404(solicitacao_id)
    novo_status = request.form['status']
    solicitacao.status = novo_status
    if novo_status == 'Comprado' and not solicitacao.data_execucao:
        solicitacao.data_execucao = datetime.utcnow()
    elif novo_status != 'Comprado':
        solicitacao.data_execucao = None
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/baixar_relatorio/<fornecedor_nome>')
def baixar_relatorio(fornecedor_nome):
    status_pendentes = ['Aguardando Aprovação', 'Em Cotação']
    pedidos = SolicitacaoCompra.query.join(Fornecedor).filter(
        Fornecedor.nome == fornecedor_nome,
        SolicitacaoCompra.status.in_(status_pendentes)
    ).all()
    if not pedidos:
        return redirect(url_for('index'))
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Produto', 'Marca', 'Código', 'Quantidade', 'Observação'])
    for pedido in pedidos:
        writer.writerow([pedido.produto_nome, pedido.marca, pedido.codigo, pedido.quantidade, pedido.observacao])
    csv_data = output.getvalue()
    output.close()
    return Response(
        csv_data.encode('utf-8'),
        mimetype="text/csv",
        headers={"Content-disposition":
                 f"attachment; filename=relatorio_{fornecedor_nome.replace(' ', '_')}.csv"}
    )

# --- EXECUÇÃO E SETUP INICIAL ---
setup_database(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=81)