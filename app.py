import os
import io
import re  # Importando o módulo para expressões regulares
import google.generativeai as genai
from datetime import datetime
import json
import streamlit as st
from pathlib import Path

def inicializar_gemini():
    """Inicializa a configuração do Gemini usando a chave API do Streamlit Secrets"""
    try:
        # Obtém a chave da API do Google dos secrets
        api_key = st.secrets["google_api_key"]
        if api_key:
            genai.configure(api_key=api_key)
            return True
    except KeyError:
        st.error("A chave API do Google não foi encontrada nos Secrets!")
        return False

def configurar_modelo():
    """Configura e retorna o modelo Gemini 1.5 Flash"""
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
        # Envia o prompt e a imagem para o modelo Gemini
        response = modelo.generate_content([ 
            prompt,
            {'mime_type': 'application/pdf', 'data': imagem_bytes}  # Envia o PDF diretamente
        ])
        
        # Processa a resposta JSON
        texto_resposta = response.text
        texto_resposta = re.sub(r'```json\n?|\n?```', '', texto_resposta)
        dados = json.loads(texto_resposta)
        return dados
    except Exception as e:
        st.error(f"Erro na análise com Gemini: {e}")
        return {"nome": None, "data": None}

def formatar_data(data_str):
    """Formata a data para o padrão DDMMYYYY"""
    if not data_str:
        return "DDMMYYYY"
    
    numeros = re.sub(r'[^\d]', '', data_str)
    
    if len(numeros) == 8:
        return numeros
    
    try:
        for formato in ['%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d']:
            try:
                data_obj = datetime.strptime(data_str, formato)
                return data_obj.strftime('%d%m%Y')
            except ValueError:
                continue
    except Exception:
        return "DDMMYYYY"
    
    return "DDMMYYYY"

def validar_nome_arquivo(nome):
    """Limpa e valida o nome do arquivo"""
    nome_limpo = re.sub(r'[<>:"/\\|?*]', '', nome)
    nome_limpo = re.sub(r'\s+', ' ', nome_limpo).strip()
    
    max_length = 240
    if len(nome_limpo) > max_length:
        nome_limpo = nome_limpo[:max_length]
    
    return nome_limpo

def processar_arquivo(arquivo_pdf, modelo):
    """Processa um único arquivo PDF"""
    try:
        # Lê o arquivo PDF como bytes
        arquivo_bytes = arquivo_pdf.read()

        with st.spinner('Extraindo informações do documento...'):
            dados = extrair_informacoes_gemini(arquivo_bytes, modelo)

        nome_funcionario = dados.get('nome', 'INDEFINIDO')
        data_exame = formatar_data(dados.get('data'))

        if nome_funcionario in [None, 'INDEFINIDO'] or data_exame == "DDMMYYYY":
            st.warning("Não foi possível extrair todas as informações necessárias.")
            st.write(f"Nome encontrado: {nome_funcionario}")
            st.write(f"Data encontrada: {data_exame}")
            return False, None

        novo_nome = f"ASO {data_exame} {nome_funcionario}.pdf"
        novo_nome = validar_nome_arquivo(novo_nome)

        # Caminho para salvar o novo arquivo
        novo_caminho = Path(f"temp/{novo_nome}")

        # Salvar o PDF renomeado
        with open(novo_caminho, "wb") as f:
            f.write(arquivo_bytes)

        # Retorna o caminho do novo arquivo
        return True, novo_caminho

    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
        return False, None

def main():
    st.title("Renomeador de ASOs")
    st.write("Este aplicativo renomeia automaticamente arquivos de Atestados de Saúde Ocupacional (ASOs).")

    # Inicialização do Gemini
    if not inicializar_gemini():
        st.warning("Por favor, insira sua chave API do Google no painel lateral.")
        return

    # Upload de arquivos (agora aceita PDF)
    arquivos = st.file_uploader(
        "Selecione os arquivos PDF dos ASOs",
        type=['pdf'],
        accept_multiple_files=True
    )

    if arquivos:
        modelo = configurar_modelo()
        
        with st.expander("📊 Resumo do Processamento", expanded=True):
            col1, col2 = st.columns(2)
            total = len(arquivos)
            sucessos = 0
            
            with col1:
                progress_bar = st.progress(0)
                status_text = st.empty()

            for i, arquivo in enumerate(arquivos):
                # Processa o arquivo PDF
                sucesso, novo_arquivo = processar_arquivo(arquivo, modelo)
                if sucesso:
                    sucessos += 1
                    # Exibe o botão de download
                    with open(novo_arquivo, "rb") as f:
                        st.download_button(
                            label="Baixar arquivo renomeado",
                            data=f,
                            file_name=novo_arquivo.name,
                            mime="application/pdf"
                        )

                # Atualiza a barra de progresso
                progress = (i + 1) / total
                progress_bar.progress(progress)
                status_text.text(f"Processando: {i+1} de {total}")

            with col2:
                st.metric("Arquivos Processados", f"{sucessos}/{total}")
                
        if sucessos == total:
            st.balloons()

if __name__ == "__main__":
    main()
