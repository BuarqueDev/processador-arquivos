import os
import io
import re
from datetime import datetime
import json
import streamlit as st
from pathlib import Path
import PyPDF2
import google.generativeai as genai
import zipfile
from PIL import Image
import fitz  # PyMuPDF

def inicializar_gemini():
    """Inicializa a configuração do Gemini usando a chave API do Streamlit Secrets"""
    try:
        api_key = st.secrets["google_api_key"]
        if api_key:
            genai.configure(api_key=api_key)
            return True
    except KeyError:
        st.error("A chave API do Google não foi encontrada nos Secrets!")
        return False

def configurar_modelo():
    """Configura e retorna o modelo Gemini"""
    return genai.GenerativeModel('gemini-1.5-flash')

def extrair_informacoes_gemini(imagem_bytes, modelo):
    """Extrai informações do ASO usando o Gemini"""
    prompt = """
    Analise esta imagem de um Atestado de Saúde Ocupacional (ASO) e extraia as seguintes informações:
    1. Nome completo do funcionário
    2. Data do exame
    
    Retorne APENAS um JSON no seguinte formato:
    {
        "nome": "NOME COMPLETO DO FUNCIONÁRIO",
        "data": "DD/MM/YYYY"
    }
    
    Se não encontrar alguma informação, use null como valor.
    """
    
    try:
        response = modelo.generate_content([
            prompt,
            {'mime_type': 'application/pdf', 'data': imagem_bytes}
        ])
        
        texto_resposta = response.text
        texto_resposta = re.sub(r'```json\n?|\n?```', '', texto_resposta)
        dados = json.loads(texto_resposta)
        return dados
    except Exception as e:
        st.error(f"Erro na análise com Gemini: {e}")
        return {"nome": None, "data": None}

def formatar_data(data_str):
    """Formata a data para o padrão DDMMYYYY, lidando com diversos formatos"""
    if not data_str:
        return "DDMMYYYY"
    
    # Remove caracteres não numéricos mantendo as barras
    numeros = re.sub(r'[^\d/]', '', data_str)
    
    # Trata diferentes formatos de data
    formatos_possiveis = [
        '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d',
        '%d/%m/%y', '%d-%m-%y',
        '%-d/%-m/%Y', '%-d/%-m/%y'  # Para datas sem zero à esquerda
    ]
    
    for formato in formatos_possiveis:
        try:
            # Primeiro, padroniza a data para o formato com barras
            if '-' in data_str:
                data_str = data_str.replace('-', '/')
            
            # Tenta converter a data
            data_obj = datetime.strptime(data_str, formato)
            
            # Garante que o ano tenha 4 dígitos
            if data_obj.year < 100:
                data_obj = data_obj.replace(year=data_obj.year + 2000)
            
            # Retorna no formato desejado
            return data_obj.strftime('%d%m%Y')
        except ValueError:
            continue
    
    return "DDMMYYYY"

def validar_nome_arquivo(nome):
    """Limpa e valida o nome do arquivo"""
    nome_limpo = re.sub(r'[<>:"/\\|?*]', '', nome)
    nome_limpo = re.sub(r'\s+', ' ', nome_limpo).strip()
    
    max_length = 240
    if len(nome_limpo) > max_length:
        nome_limpo = nome_limpo[:max_length]
    
    return nome_limpo

def dividir_pdf(arquivo_pdf, opcoes_divisao, usar_ia=False, modelo=None):
    """Divide um PDF conforme as opções especificadas e opcionalmente renomeia usando IA"""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(arquivo_pdf))
        total_paginas = len(pdf_reader.pages)
        pdfs_divididos = []
        
        modo = opcoes_divisao["modo"]
        
        if modo == "paginas_fixas":
            paginas_por_arquivo = opcoes_divisao["paginas_por_arquivo"]
            for i in range(0, total_paginas, paginas_por_arquivo):
                pdf_writer = PyPDF2.PdfWriter()
                fim = min(i + paginas_por_arquivo, total_paginas)
                
                for j in range(i, fim):
                    pdf_writer.add_page(pdf_reader.pages[j])
                
                output = io.BytesIO()
                pdf_writer.write(output)
                output_bytes = output.getvalue()
                
                if usar_ia and modelo:
                    dados = extrair_informacoes_gemini(output_bytes, modelo)
                    nome_funcionario = dados.get('nome', 'INDEFINIDO')
                    data_exame = formatar_data(dados.get('data'))
                    if nome_funcionario not in [None, 'INDEFINIDO'] and data_exame != "DDMMYYYY":
                        nome_arquivo = f"ASO {data_exame} {nome_funcionario}.pdf"
                    else:
                        nome_arquivo = f"parte_{(i//paginas_por_arquivo)+1}.pdf"
                else:
                    nome_arquivo = f"parte_{(i//paginas_por_arquivo)+1}.pdf"
                
                pdfs_divididos.append((nome_arquivo, output_bytes))
        
        elif modo == "intervalo_personalizado":
            intervalos = opcoes_divisao["intervalos"]
            for idx, intervalo in enumerate(intervalos):
                try:
                    inicio, fim = map(int, intervalo.split('-'))
                    if 1 <= inicio <= fim <= total_paginas:
                        pdf_writer = PyPDF2.PdfWriter()
                        for i in range(inicio-1, fim):
                            pdf_writer.add_page(pdf_reader.pages[i])
                        output = io.BytesIO()
                        pdf_writer.write(output)
                        output_bytes = output.getvalue()
                        
                        if usar_ia and modelo:
                            dados = extrair_informacoes_gemini(output_bytes, modelo)
                            nome_funcionario = dados.get('nome', 'INDEFINIDO')
                            data_exame = formatar_data(dados.get('data'))
                            if nome_funcionario not in [None, 'INDEFINIDO'] and data_exame != "DDMMYYYY":
                                nome_arquivo = f"ASO {data_exame} {nome_funcionario}.pdf"
                            else:
                                nome_arquivo = f"intervalo_{inicio}_a_{fim}.pdf"
                        else:
                            nome_arquivo = f"intervalo_{inicio}_a_{fim}.pdf"
                        
                        pdfs_divididos.append((nome_arquivo, output_bytes))
                except ValueError:
                    st.warning(f"Intervalo inválido ignorado: {intervalo}")
        
        elif modo == "paginas_individuais":
            for i in range(total_paginas):
                pdf_writer = PyPDF2.PdfWriter()
                pdf_writer.add_page(pdf_reader.pages[i])
                output = io.BytesIO()
                pdf_writer.write(output)
                output_bytes = output.getvalue()
                
                if usar_ia and modelo:
                    dados = extrair_informacoes_gemini(output_bytes, modelo)
                    nome_funcionario = dados.get('nome', 'INDEFINIDO')
                    data_exame = formatar_data(dados.get('data'))
                    if nome_funcionario not in [None, 'INDEFINIDO'] and data_exame != "DDMMYYYY":
                        nome_arquivo = f"ASO {data_exame} {nome_funcionario}.pdf"
                    else:
                        nome_arquivo = f"pagina_{i+1}.pdf"
                else:
                    nome_arquivo = f"pagina_{i+1}.pdf"
                
                pdfs_divididos.append((nome_arquivo, output_bytes))
                
        elif modo == "extrair_paginas":
            paginas = opcoes_divisao["paginas"]
            for pagina in paginas:
                try:
                    num_pagina = int(pagina)
                    if 1 <= num_pagina <= total_paginas:
                        pdf_writer = PyPDF2.PdfWriter()
                        pdf_writer.add_page(pdf_reader.pages[num_pagina-1])
                        output = io.BytesIO()
                        pdf_writer.write(output)
                        output_bytes = output.getvalue()
                        
                        if usar_ia and modelo:
                            dados = extrair_informacoes_gemini(output_bytes, modelo)
                            nome_funcionario = dados.get('nome', 'INDEFINIDO')
                            data_exame = formatar_data(dados.get('data'))
                            if nome_funcionario not in [None, 'INDEFINIDO'] and data_exame != "DDMMYYYY":
                                nome_arquivo = f"ASO {data_exame} {nome_funcionario}.pdf"
                            else:
                                nome_arquivo = f"pagina_{num_pagina}.pdf"
                        else:
                            nome_arquivo = f"pagina_{num_pagina}.pdf"
                        
                        pdfs_divididos.append((nome_arquivo, output_bytes))
                except ValueError:
                    st.warning(f"Número de página inválido ignorado: {pagina}")
        
        return True, pdfs_divididos
    except Exception as e:
        st.error(f"Erro ao dividir PDF: {e}")
        return False, None
    
def interface_divisao_pdf():
    """Interface para configuração da divisão de PDFs"""
    st.sidebar.subheader("Configurações de Divisão")
    
    modo = st.sidebar.radio(
        "Escolha o modo de divisão:",
        ["paginas_fixas", "intervalo_personalizado", "paginas_individuais", "extrair_paginas"],
        format_func=lambda x: {
            "paginas_fixas": "Dividir em grupos fixos de páginas",
            "intervalo_personalizado": "Dividir por intervalos personalizados",
            "paginas_individuais": "Uma página por arquivo",
            "extrair_paginas": "Extrair páginas específicas"
        }[x]
    )
    
    opcoes = {"modo": modo}
    
    if modo == "paginas_fixas":
        opcoes["paginas_por_arquivo"] = st.sidebar.number_input(
            "Páginas por arquivo",
            min_value=1,
            value=2
        )
    
    elif modo == "intervalo_personalizado":
        num_intervalos = st.sidebar.number_input(
            "Número de intervalos",
            min_value=1,
            value=1
        )
        intervalos = []
        for i in range(num_intervalos):
            intervalo = st.sidebar.text_input(
                f"Intervalo {i+1} (ex: 1-3)",
                value="1-2"
            )
            intervalos.append(intervalo)
        opcoes["intervalos"] = intervalos
    
    elif modo == "extrair_paginas":
        paginas = st.sidebar.text_input(
            "Páginas para extrair (separadas por vírgula)",
            value="1,3,5"
        )
        opcoes["paginas"] = [p.strip() for p in paginas.split(",")]
    
    return opcoes

def criar_zip(arquivos):
    """Cria um arquivo ZIP com os PDFs processados"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for nome_arquivo, conteudo in arquivos:
            zip_file.writestr(nome_arquivo, conteudo)
    
    return zip_buffer.getvalue()

def criar_thumbnail_pdf(pdf_bytes, max_size=(150, 150), page_number=0):
    """Cria uma thumbnail de uma página específica do PDF"""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if 0 <= page_number < len(doc):
            pix = doc[page_number].get_pixmap(matrix=fitz.Matrix(1, 1))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img.thumbnail(max_size)
            return img
    except Exception as e:
        st.error(f"Erro ao criar thumbnail: {e}")
        return None

def juntar_pdfs(arquivos_pdf):
    """Junta múltiplos PDFs em um único arquivo"""
    merger = PyPDF2.PdfMerger()
    
    try:
        for arquivo in arquivos_pdf:
            pdf_bytes = io.BytesIO(arquivo.read())
            merger.append(pdf_bytes)
        
        output = io.BytesIO()
        merger.write(output)
        merger.close()
        return output.getvalue()
    except Exception as e:
        st.error(f"Erro ao juntar PDFs: {e}")
        return None

def renomear_arquivo(arquivo_bytes, novo_nome):
    """Renomeia um único arquivo PDF"""
    return (f"{novo_nome}.pdf", arquivo_bytes)

def main():
    st.title("Processador Avançado de PDFs")
    
    tab1, tab2, tab3 = st.tabs([
        "Dividir PDF", 
        "Renomear ASOs",
        "Juntar PDFs"
    ])
    
    with tab1:
        st.header("Dividir PDF")
        arquivo_divisao = st.file_uploader(
            "Selecione o PDF para dividir",
            type=['pdf'],
            key="divisao"
        )
        
        if arquivo_divisao:
            arquivo_bytes = arquivo_divisao.read()
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(arquivo_bytes))
            total_paginas = len(pdf_reader.pages)
            
            st.write(f"Total de páginas: {total_paginas}")
            
            # Criar grid de miniaturas
            num_colunas = 5  # 5 colunas para ter 2 linhas de 5 miniaturas
            colunas = st.columns(num_colunas)
            
            # Mostrar até 10 páginas
            paginas_mostrar = min(10, total_paginas)
            for i in range(paginas_mostrar):
                with colunas[i % num_colunas]:
                    thumbnail = criar_thumbnail_pdf(arquivo_bytes, page_number=i)
                    if thumbnail:
                        st.image(thumbnail, caption=f"Página {i+1}")
            
            opcoes_divisao = interface_divisao_pdf()
            
            # Opções de renomeação
            col1, col2 = st.columns(2)
            with col1:
                usar_ia = st.checkbox("Usar IA para renomear (ASOs)")
            with col2:
                renomear_padrao = st.checkbox("Renomear com padrão personalizado")
            
            modelo = None
            if usar_ia:
                if not inicializar_gemini():
                    st.warning("Configure a chave API do Google para usar a renomeação por IA")
                    usar_ia = False
                else:
                    modelo = configurar_modelo()
            
            padrao_nome = "parte_{numero}"
            if renomear_padrao and not usar_ia:
                padrao_nome = st.text_input(
                    "Padrão para renomear (use {numero} para o número da parte)",
                    value="parte_{numero}"
                )
            
            if st.button("Dividir PDF"):
                sucesso, pdfs_divididos = dividir_pdf(arquivo_bytes, opcoes_divisao, usar_ia, modelo)
                
                if sucesso and pdfs_divididos:
                    # Renomear com padrão se necessário e se não estiver usando IA
                    if renomear_padrao and not usar_ia:
                        pdfs_divididos = [
                            (padrao_nome.format(numero=i+1) + ".pdf", conteudo)
                            for i, (_, conteudo) in enumerate(pdfs_divididos)
                        ]
                    
                    # Se for apenas um arquivo, oferecer download direto
                    if len(pdfs_divididos) == 1:
                        nome_arquivo, conteudo = pdfs_divididos[0]
                        st.download_button(
                            label=f"Baixar {nome_arquivo}",
                            data=conteudo,
                            file_name=nome_arquivo,
                            mime="application/pdf"
                        )
                    else:
                        zip_data = criar_zip(pdfs_divididos)
                        st.success(f"PDF dividido com sucesso em {len(pdfs_divididos)} partes!")
                        st.download_button(
                            label="Baixar partes (ZIP)",
                            data=zip_data,
                            file_name="pdf_dividido.zip",
                            mime="application/zip"
                        )
    
    with tab2:
        st.header("Renomear ASOs")
        if not inicializar_gemini():
            st.warning("Por favor, insira sua chave API do Google para usar esta função.")
            return
        
        modo_renomeacao = st.radio(
            "Modo de renomeação:",
            ["Automático (usando IA)", "Manual"],
            horizontal=True
        )
        
        arquivos_aso = st.file_uploader(
            "Selecione os ASOs para renomear",
            type=['pdf'],
            accept_multiple_files=True,
            key="renomear"
        )
        
        if arquivos_aso:
            todos_resultados = []
            
            if modo_renomeacao == "Automático (usando IA)":
                modelo = configurar_modelo()
                with st.expander("📊 Processamento", expanded=True):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for i, arquivo in enumerate(arquivos_aso):
                        arquivo_bytes = arquivo.read()
                        dados = extrair_informacoes_gemini(arquivo_bytes, modelo)
                        
                        nome_funcionario = dados.get('nome', 'INDEFINIDO')
                        data_exame = formatar_data(dados.get('data'))
                        
                        if nome_funcionario not in [None, 'INDEFINIDO'] and data_exame != "DDMMYYYY":
                            novo_nome = f"ASO {data_exame} {nome_funcionario}"
                            novo_nome = validar_nome_arquivo(novo_nome)
                            todos_resultados.append(renomear_arquivo(arquivo_bytes, novo_nome))
                        
                        progress = (i + 1) / len(arquivos_aso)
                        progress_bar.progress(progress)
                        status_text.text(f"Processando: {i+1} de {len(arquivos_aso)}")
            
            else:  # Modo manual
                for arquivo in arquivos_aso:
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        thumbnail = criar_thumbnail_pdf(arquivo.read())
                        if thumbnail:
                            st.image(thumbnail, caption=arquivo.name)
                    
                    with col2:
                        novo_nome = st.text_input(
                            f"Novo nome para {arquivo.name}",
                            value=arquivo.name.replace('.pdf', '')
                        )
                        if novo_nome:
                            todos_resultados.append(
                                renomear_arquivo(arquivo.read(), novo_nome)
                            )
            
            if todos_resultados:
                if len(todos_resultados) == 1:
                    nome_arquivo, conteudo = todos_resultados[0]
                    st.download_button(
                        label=f"Baixar {nome_arquivo}",
                        data=conteudo,
                        file_name=nome_arquivo,
                        mime="application/pdf"
                    )
                else:
                    zip_data = criar_zip(todos_resultados)
                    st.download_button(
                        label="Baixar ASOs renomeados (ZIP)",
                        data=zip_data,
                        file_name="asos_renomeados.zip",
                        mime="application/zip"
                    )
    
    with tab3:
        st.header("Juntar PDFs")
        arquivos_juntar = st.file_uploader(
            "Selecione os PDFs para juntar",
            type=['pdf'],
            accept_multiple_files=True,
            key="juntar"
        )
        
        if arquivos_juntar:
            st.write(f"PDFs selecionados: {len(arquivos_juntar)}")
            
            # Mostrar previews
            cols = st.columns(4)
            for i, arquivo in enumerate(arquivos_juntar):
                with cols[i % 4]:
                    thumbnail = criar_thumbnail_pdf(arquivo.read())
                    if thumbnail:
                        st.image(thumbnail, caption=arquivo.name)
                    arquivo.seek(0)  # Reset do buffer
            
            novo_nome = st.text_input(
                "Nome do arquivo final",
                value="pdfs_unidos"
            )
            
            if st.button("Juntar PDFs"):
                pdf_final = juntar_pdfs(arquivos_juntar)
                if pdf_final:
                    st.success("PDFs unidos com sucesso!")
                    st.download_button(
                        label="Baixar PDF unificado",
                        data=pdf_final,
                        file_name=f"{novo_nome}.pdf",
                        mime="application/pdf"
                    )

if __name__ == "__main__":
    main()
