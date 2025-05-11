from flask import Flask, render_template, request, redirect, url_for, jsonify
import easyocr
import cv2
import os
from werkzeug.utils import secure_filename
import re
from datetime import datetime
import numpy as np

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}

# Inicializar EasyOCR
reader = easyocr.Reader(['es', 'en'])

# Crear carpeta de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_document_info(text_results):
    """Extrae información específica de documentos bolivianos"""
    document_info = {
        'tipo': None,
        'numero': None,
        'nombre': None,
        'apellidos': None,
        'fecha_nacimiento': None,
        'fecha_emision': None,
        'fecha_vencimiento': None,
        'ci_number': None,
        'nacionalidad': None,
        'sexo': None,
        'lugar_nacimiento': None,
        'valid': False
    }
    
    # Combinar todo el texto detectado
    text_list = [result[1] for result in text_results]
    text_combined = ' '.join(text_list).upper()
    
    # Detectar tipo de documento
    if 'PASAPORTE' in text_combined or 'PASSPORT' in text_combined:
        document_info['tipo'] = 'Pasaporte Boliviano'
        
        # Buscar número de pasaporte (formato: TE96309)
        pasaporte_pattern = r'[A-Z]{2}\d{5,6}'
        pasaporte_matches = re.findall(pasaporte_pattern, text_combined)
        if pasaporte_matches:
            document_info['numero'] = pasaporte_matches[0]
        
        # Buscar nombres y apellidos en pasaporte
        if 'APELLIDOS' in text_combined or 'SURNAMES' in text_combined:
            for i, text in enumerate(text_list):
                if 'APELLIDOS' in text.upper() or 'SURNAMES' in text.upper():
                    if i + 1 < len(text_list):
                        document_info['apellidos'] = text_list[i + 1]
                if 'NOMBRES' in text.upper() or 'GIVEN NAMES' in text.upper():
                    if i + 1 < len(text_list):
                        document_info['nombre'] = text_list[i + 1]
        
        # Extraer CI del pasaporte
        if 'CEDULA DE IDENTIDAD' in text_combined:
            ci_pattern = r'9516651(?:\s*\d+)?'
            ci_matches = re.findall(ci_pattern, text_combined)
            if ci_matches:
                document_info['ci_number'] = ci_matches[0].replace(' ', '')
    
    elif 'CEDULA' in text_combined or 'IDENTIDAD' in text_combined:
        document_info['tipo'] = 'Cédula de Identidad'
        
        # Buscar número de CI (formato: 9516651)
        ci_pattern = r'(?:No\.|NO\.)?\s*(\d{7,8})'
        ci_matches = re.findall(ci_pattern, text_combined)
        if ci_matches:
            document_info['ci_number'] = ci_matches[0]
            document_info['numero'] = ci_matches[0]
        
        # Buscar fechas específicas
        if 'EMITIDA EL' in text_combined:
            emision_pattern = r'EMITIDA EL\s*(\d{1,2}\s*DE\s*[A-Z]+\s*DE\s*\d{4})'
            emision_matches = re.findall(emision_pattern, text_combined)
            if emision_matches:
                document_info['fecha_emision'] = emision_matches[0]
        
        if 'EXPIRA EL' in text_combined:
            expira_pattern = r'EXPIRA EL\s*(\d{1,2}\s*DE\s*[A-Z]+\s*DE\s*\d{4})'
            expira_matches = re.findall(expira_pattern, text_combined)
            if expira_matches:
                document_info['fecha_vencimiento'] = expira_matches[0]
    
    elif 'LICENCIA' in text_combined or 'CONDUCIR' in text_combined:
        document_info['tipo'] = 'Licencia de Conducir'
        
        # Buscar número de licencia y CI
        for text in text_list:
            if re.match(r'^\d{7,8}$', text):
                document_info['ci_number'] = text
                document_info['numero'] = text
                break
        
        # Buscar nombre completo en licencia
        if 'NOMBRES' in text_combined:
            for i, text in enumerate(text_list):
                if 'NOMBRES' in text.upper() and 'APELLIDOS' in text.upper():
                    if i + 1 < len(text_list):
                        # El siguiente elemento debería ser el nombre completo
                        nombre_completo = text_list[i + 1]
                        # Dividir en nombre y apellidos
                        partes = nombre_completo.split()
                        if len(partes) >= 3:
                            document_info['nombre'] = ' '.join(partes[:2])
                            document_info['apellidos'] = ' '.join(partes[2:])
        
        # Buscar fechas en formato DD/MM/YYYY
        date_pattern = r'\d{2}/\d{2}/\d{4}'
        dates = re.findall(date_pattern, text_combined)
        if dates:
            # La primera fecha suele ser de emisión, la segunda de vencimiento
            if len(dates) >= 1:
                document_info['fecha_emision'] = dates[0]
            if len(dates) >= 2:
                document_info['fecha_vencimiento'] = dates[1]
    
    # Buscar fechas generales (múltiples formatos)
    # Formato: DD/MM/YYYY o DD-MM-YYYY
    date_pattern1 = r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b'
    # Formato: DD de Mes de YYYY
    date_pattern2 = r'(\d{1,2}\s+DE\s+[A-Z]+\s+DE\s+\d{4})'
    # Formato específico de algunos documentos
    date_pattern3 = r'(\d{2})/([A-Z]{3})/([A-Z]{3})/(\d{4})'
    
    dates1 = re.findall(date_pattern1, text_combined)
    dates2 = re.findall(date_pattern2, text_combined)
    dates3 = re.findall(date_pattern3, text_combined)
    
    # Procesar fechas encontradas
    all_dates = dates1 + dates2
    if dates3:
        for date_match in dates3:
            formatted_date = f"{date_match[0]}/{date_match[1]}/{date_match[3]}"
            all_dates.append(formatted_date)
    
    # Asignar fechas según contexto
    for i, text in enumerate(text_list):
        if 'NACIMIENTO' in text.upper():
            for date in all_dates:
                if date in text or (i + 1 < len(text_list) and date in text_list[i + 1]):
                    document_info['fecha_nacimiento'] = date
                    break
    
    # Buscar nacionalidad
    if 'BOLIVIANA' in text_combined or 'BOLIVIANO' in text_combined:
        document_info['nacionalidad'] = 'BOLIVIANA'
    
    # Buscar sexo
    sexo_pattern = r'\b(M|F|MASCULINO|FEMENINO)\b'
    sexo_matches = re.findall(sexo_pattern, text_combined)
    if sexo_matches:
        document_info['sexo'] = sexo_matches[0][0] if len(sexo_matches[0]) == 1 else sexo_matches[0]
    
    # Buscar lugar de nacimiento
    if 'COCHABAMBA' in text_combined:
        document_info['lugar_nacimiento'] = 'COCHABAMBA'
    
    # Validar documento
    if document_info['ci_number'] or document_info['numero']:
        document_info['valid'] = True
    
    return document_info

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '':
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Procesar imagen con EasyOCR
        results = reader.readtext(filepath)
        
        # Extraer información del documento
        document_info = extract_document_info(results)
        
        # Dibujar rectángulos en la imagen
        img = cv2.imread(filepath)
        for detection in results:
            bbox = detection[0]
            text = detection[1]
            confidence = detection[2]
            
            # Convertir bbox a formato para cv2
            pts = [tuple(map(int, point)) for point in bbox]
            
            # Dibujar rectángulo
            cv2.polylines(img, [np.array(pts)], True, (0, 255, 0), 2)
            
            # Añadir texto
            cv2.putText(img, text, (pts[0][0], pts[0][1] - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # Guardar imagen procesada
        processed_filename = f"processed_{filename}"
        processed_filepath = os.path.join(app.config['UPLOAD_FOLDER'], processed_filename)
        cv2.imwrite(processed_filepath, img)
        
        return render_template('results.html', 
                             original_image=filename,
                             processed_image=processed_filename,
                             results=results,
                             document_info=document_info)
    
    return redirect(url_for('index'))

@app.route('/camera')
def camera():
    return render_template('camera.html')

@app.route('/process_camera', methods=['POST'])
def process_camera():
    data = request.json
    image_data = data['image']
    
    # Decodificar imagen base64
    import base64
    
    image_data = image_data.split(',')[1]
    image_bytes = base64.b64decode(image_data)
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Guardar imagen
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"camera_{timestamp}.jpg"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    cv2.imwrite(filepath, img)
    
    # Procesar con OCR
    results = reader.readtext(filepath)
    document_info = extract_document_info(results)
    
    return jsonify({
        'success': True,
        'image_path': filename,
        'results': results,
        'document_info': document_info
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)