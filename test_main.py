import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main


def _mensaje(message_id, message_type, content="", attachments=None, metadata=None):
    return {
        "id": message_id,
        "message_type": message_type,
        "content": content,
        "attachments": attachments or [],
        "content_attributes": metadata or {},
        "private": False,
    }


def _imagen(url, size, width=1000, height=600):
    return {
        "file_type": "image",
        "data_url": url,
        "file_size": size,
        "width": width,
        "height": height,
    }


def _metadata_seguimiento(sequence):
    return {
        "data": {
            main.FOLLOWUP_METADATA_KEY: {
                "kind": "followup",
                "sequence": sequence,
            }
        }
    }


def _metadata_bot(followup_closed=False):
    return {
        "data": {
            main.FOLLOWUP_METADATA_KEY: {
                "kind": "bot_reply",
                "followup_closed": followup_closed,
            }
        }
    }


def _conversacion_activa(**overrides):
    data = {"labels": [], "status": "open", "can_reply": True}
    data.update(overrides)
    return data


def _ficha_consumidor_completa():
    return {
        "Tipo de portabilidad": "Portabilidad",
        "Tipo de cliente": "Consumidor final",
        "Nombre": "Ana María Pérez",
        "Compañía actual": "Movistar",
        "Número a portar": "2235551234",
        "Plan elegido": "4 GB",
        "Localidad": "Mar del Plata",
        "Provincia": "Buenos Aires",
        "Dirección": "San Martín 1234",
        "Código postal": "7600",
    }


class ReglasDeNegocioTest(unittest.TestCase):
    def _ficha_consumidor_completa(self):
        return _ficha_consumidor_completa()

    def test_precios_consumidor_final_distinguen_movistar_y_personal(self):
        movistar_tuenti = main.SYSTEM_PROMPT.split(
            "28. CONSUMIDOR FINAL — MOVISTAR / TUENTI", 1
        )[1].split("29. EMPRESA — MOVISTAR / TUENTI", 1)[0]
        personal = main.SYSTEM_PROMPT.split(
            "31. CONSUMIDOR FINAL — PERSONAL", 1
        )[1].split("32. CONSUMIDOR FINAL — LÍNEA NUEVA", 1)[0]
        tabla_movistar_65 = (
            "4 GB → $20.997",
            "7 GB → $23.870",
            "10 GB → $30.345",
            "30 GB → $40.460",
            "50 GB → $46.529",
        )
        tabla_personal_70 = (
            "4 GB → $17.997",
            "7 GB → $20.460",
            "10 GB → $26.010",
            "30 GB → $34.680",
            "50 GB → $39.882",
        )

        self.assertIn("65% OFF", movistar_tuenti)
        for precio in tabla_movistar_65:
            self.assertIn(precio, movistar_tuenti)

        self.assertIn("70% OFF", personal)
        for precio in tabla_personal_70:
            self.assertIn(precio, personal)
        for beneficio in (
            "+10 GB de regalo durante 6 meses, en todos los planes",
            "WhatsApp gratis",
            "llamadas ilimitadas",
            "roaming internacional",
            "pack de GB al 50%",
            "1 mes de regalo de Disney+ y Prime Video",
            "3 meses de regalo de YouTube Premium",
        ):
            self.assertIn(beneficio, personal)

        self.assertNotIn("70% OFF", movistar_tuenti)
        self.assertNotIn("65% OFF", personal)
        self.assertIn("El plan de 2 GB ya no existe", personal)

    def test_solo_pedir_datos_no_habilita_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame nombre completo, localidad y dirección"),
            _mensaje(2, 0, "dale"),
        ]
        self.assertFalse(main._cliente_ya_paso_datos(messages))

    def test_un_dato_del_cliente_habilita_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame nombre completo, localidad y dirección"),
            _mensaje(2, 0, "Mar del Plata"),
        ]
        self.assertTrue(main._cliente_ya_paso_datos(messages))

    def test_explicar_portabilidad_no_equivale_a_iniciar_checklist(self):
        messages = [
            _mensaje(1, 1, "podés portar tu línea manteniendo el mismo número"),
            _mensaje(2, 0, "quiero el de 30 GB"),
        ]
        self.assertFalse(main._cliente_ya_paso_datos(messages))

    def test_dato_proactivo_tambien_habilita_seguimiento(self):
        self.assertTrue(main._cliente_ya_paso_datos([
            _mensaje(1, 0, "mi DNI es 12345678"),
            _mensaje(2, 1, "perfecto, qué localidad es?", metadata=_metadata_bot()),
        ]))
        self.assertTrue(main._cliente_ya_paso_datos([
            _mensaje(1, 0, "mi email: cliente@ejemplo.com"),
        ]))

    def test_imagen_ajena_al_checklist_no_habilita_seguimiento(self):
        messages = [
            _mensaje(1, 0, "mirá esta promo", attachments=[_imagen("promo", 10)]),
            _mensaje(2, 1, "pasame nombre completo, DNI y fotos frente y dorso"),
            _mensaje(3, 0, "dame un rato"),
            _mensaje(4, 1, "dale, espero las fotos"),
        ]
        self.assertFalse(main._cliente_ya_paso_datos(messages))

    def test_adjunto_solo_cuenta_con_contexto_de_documentacion(self):
        solicitado = [
            _mensaje(1, 1, "pasame nombre completo, DNI y fotos frente y dorso"),
            _mensaje(2, 0, attachments=[_imagen("dni-frente", 10)]),
        ]
        proactivo_identificado = [
            _mensaje(1, 0, "te mando mi DNI", attachments=[_imagen("dni", 10)]),
        ]
        sin_contexto = [
            _mensaje(1, 0, attachments=[_imagen("imagen-cualquiera", 10)]),
        ]
        self.assertTrue(main._cliente_ya_paso_datos(solicitado))
        self.assertTrue(main._cliente_ya_paso_datos(proactivo_identificado))
        self.assertFalse(main._cliente_ya_paso_datos(sin_contexto))

    def test_factura_no_cuenta_aunque_se_haya_pedido_dni(self):
        messages = [
            _mensaje(1, 1, "pasame nombre completo, DNI y fotos frente y dorso"),
            _mensaje(2, 0, "esta es mi factura", attachments=[_imagen("factura", 10)]),
        ]
        self.assertFalse(main._cliente_ya_paso_datos(messages))

    def test_webhook_duplicado_se_detecta_sin_reprocesarlo(self):
        message_id = "prueba-duplicado-999"
        main._seen_incoming_message_ids.pop(message_id, None)
        self.assertTrue(main._registrar_webhook_entrante(message_id))
        self.assertFalse(main._registrar_webhook_entrante(message_id))
        main._seen_incoming_message_ids.pop(message_id, None)

    def test_dos_burbujas_del_mismo_seguimiento_cuentan_una(self):
        messages = [
            _mensaje(1, 1, "primera", metadata=_metadata_seguimiento(1)),
            _mensaje(2, 1, "segunda", metadata=_metadata_seguimiento(1)),
            _mensaje(3, 1, "otro", metadata=_metadata_seguimiento(2)),
        ]
        self.assertEqual(main._followups_enviados(messages), 2)

    def test_secuencia_dos_sola_igual_bloquea_un_tercero(self):
        messages = [
            _mensaje(3, 1, "segundo", metadata=_metadata_seguimiento(2)),
        ]
        self.assertEqual(main._followups_enviados(messages), 2)

    def test_estado_de_fotos_exige_dos_imagenes_distintas(self):
        una = [_mensaje(1, 0, attachments=[_imagen("frente", 100)])]
        repetida = [
            _mensaje(1, 0, attachments=[_imagen("frente", 100)]),
            _mensaje(2, 0, attachments=[_imagen("frente-reenviado", 100)]),
        ]
        dos = repetida + [_mensaje(3, 0, attachments=[_imagen("dorso", 200)])]
        self.assertEqual(main._estado_fotos_dni([]), 0)
        self.assertEqual(main._estado_fotos_dni(una), 1)
        self.assertEqual(main._estado_fotos_dni(repetida), 1)
        self.assertEqual(main._estado_fotos_dni(dos), 2)

    def test_un_pdf_cuenta_como_frente_y_dorso(self):
        pdf = {
            "file_type": "file",
            "extension": "pdf",
            "data_url": "dni.pdf",
        }
        self.assertEqual(main._estado_fotos_dni([_mensaje(1, 0, attachments=[pdf])]), 2)

    def test_detecta_variantes_de_foto_pendiente_solo_despues_de_pedirla(self):
        pedido = _mensaje(1, 1, "para cerrar mandame foto del frente y dorso del DNI")
        variantes = (
            "no lo tengo a mano",
            "ahora no tengo el DNI conmigo",
            "no la tengo ahora",
            "no las puedo mandar desde el teléfono",
            "prefiero no mandar fotos por acá",
            "te las paso más tarde",
            "se las mando a Camila",
            "se las paso a tu jefa",
            "no me deja adjuntar las imágenes",
            "mejor termino esto presencial",
        )
        for texto in variantes:
            with self.subTest(texto=texto):
                self.assertTrue(main._cliente_dejo_foto_dni_pendiente([
                    pedido,
                    _mensaje(2, 0, texto),
                ]))

        self.assertFalse(main._cliente_dejo_foto_dni_pendiente([
            _mensaje(1, 0, "no lo tengo a mano"),
        ]))
        self.assertFalse(main._cliente_dejo_foto_dni_pendiente([
            pedido,
            _mensaje(2, 0, "ok, ahora las busco"),
        ]))
        self.assertFalse(main._cliente_dejo_foto_dni_pendiente([
            pedido,
            _mensaje(2, 0, "no tengo problema, ya te las mando"),
        ]))

    def test_fotos_completas_tienen_prioridad_sobre_mensaje_anterior_de_espera(self):
        messages = [
            _mensaje(1, 1, "mandame foto del frente y dorso del DNI"),
            _mensaje(2, 0, "te las paso más tarde"),
            _mensaje(3, 0, attachments=[
                _imagen("dni-frente", 101),
                _imagen("dni-dorso", 102),
            ]),
        ]
        self.assertFalse(main._cliente_dejo_foto_dni_pendiente(messages))

    def test_aviso_de_foto_pendiente_se_inserta_antes_de_la_ficha(self):
        respuesta = (
            "perfecto, ya registré tus datos\n---\n"
            "Hola Camila, quiero avanzar con una portabilidad.\nNombre: Ana"
        )
        actualizada = main._agregar_aviso_foto_pendiente(respuesta)
        parte_publica, ficha = actualizada.split("Hola Camila, quiero avanzar", 1)
        self.assertIn("mi jefa", parte_publica)
        self.assertIn("fotos del frente y dorso del DNI", parte_publica)
        self.assertIn(main.NUMERO_CAMILA, parte_publica)
        self.assertIn("Nombre: Ana", ficha)

    def test_prompt_permite_derivar_si_la_foto_queda_pendiente(self):
        self.assertIn("FOTO_DNI nunca bloquea: se deriva sin esperar respuesta", main.SYSTEM_PROMPT)
        self.assertIn("No esperes una respuesta ni una foto para derivar", main.SYSTEM_PROMPT)
        self.assertIn("si no, lo terminás con ella directamente", main.SYSTEM_PROMPT)
        self.assertNotIn("OBLIGATORIA — BLOQUEA EL HANDOFF", main.SYSTEM_PROMPT)
        self.assertNotIn("NO se deriva a Camila (no se genera la", main.SYSTEM_PROMPT)

    def test_filtra_el_razonamiento_interno_observado(self):
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "**Validating Current Status**\nThe user has supplied the information."
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "**Análisis de la conversación**\nEl cliente ya pasó todos los datos."
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "<analysis>Debo decidir qué contestar</analysis> hola"
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "1. Analizar el mensaje del cliente\n2. Preparar la respuesta"
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "mandale ese mensaje y esperá.\n\n[INTERNAL_NOTE]"
        ))
        self.assertFalse(main._tiene_razonamiento_filtrado(
            "perfecto, me falta solamente la foto del dorso"
        ))

    def test_bloquea_codigo_postal_no_informado_por_el_cliente(self):
        historial = [
            _mensaje(1, 1, "me decís la provincia y el código postal?"),
            _mensaje(2, 0, "Tucumán"),
        ]
        motivo = main._motivo_respuesta_incoherente(
            "listo. el código postal de Lules es 4129, correcto?", historial
        )
        self.assertIn("código postal", motivo)
        self.assertIn("4129", motivo)

    def test_permite_repetir_codigo_postal_informado_por_el_cliente(self):
        historial = [
            _mensaje(1, 1, "me decís la provincia y el código postal?"),
            _mensaje(2, 0, "Tucumán, código 4128"),
        ]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "perfecto, anoté el código postal 4128", historial
        ))

    def test_prompt_prohibe_inferir_el_codigo_postal(self):
        self.assertIn("CÓDIGO POSTAL — REGLA CRÍTICA", main.SYSTEM_PROMPT)
        self.assertIn("NUNCA lo deduzcas, completes", main.SYSTEM_PROMPT)

    def test_prompt_exige_solo_la_salida_destinada_al_cliente(self):
        self.assertIn("CONTRATO FINAL DE SALIDA — PRIORIDAD MÁXIMA", main.SYSTEM_PROMPT)
        self.assertIn("Entregá únicamente la respuesta destinada al cliente", main.SYSTEM_PROMPT)
        self.assertIn("Pensá y resolvé todo internamente", main.SYSTEM_PROMPT)

    def test_filtra_narracion_de_silencio_observada_en_bot3(self):
        casos = [
            '*Valentina no responde. El "Gracias" del cliente cierra la conversación.*',
            "Valentina no responde. El usuario continúa con comentarios políticos.",
            "El bot no responde porque la conversación comercial ha concluido.",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertTrue(main._tiene_razonamiento_filtrado(texto))

    def test_filtra_marcador_de_ficha_interna_observado_en_bot4(self):
        texto = (
            "ya le pasé tus datos a mi jefa\n\n"
            "*[Ficha interna generada para el equipo. El cliente no ve este mensaje.]*"
        )
        self.assertTrue(main._tiene_razonamiento_filtrado(texto))

    def test_sanitiza_marcadores_internos_antes_del_envio(self):
        texto = (
            "ya le pasé todos tus datos a mi jefa.\n\n"
            "*[Ficha interna generada para el equipo. El cliente no ve este mensaje.]*"
        )
        self.assertEqual(
            main._sanitizar_burbuja_publica(texto),
            "ya le pasé todos tus datos a mi jefa.",
        )
        self.assertEqual(
            main._sanitizar_burbuja_publica("tu plan incluye [10 GB] por mes"),
            "tu plan incluye [10 GB] por mes",
        )

    def test_dos_lineas_nuevas_del_mismo_contacto_no_se_pisan(self):
        veronica = main._clave_registro_sheets(
            "LÍNEA NUEVA", "+5493624030510", "Piriz Verónica Vanesa", "31142619", "2 GB"
        )
        norma = main._clave_registro_sheets(
            "LÍNEA NUEVA", "+5493624030510", "Cabrera Norma Graciela", "23273999", "30 GB"
        )
        self.assertNotEqual(veronica, norma)
        self.assertEqual(
            veronica,
            main._clave_registro_sheets(
                "linea nueva", "3624030510", "OTRO ORDEN DE NOMBRE", "31.142.619", "30 gb"
            ),
        )

    def test_portabilidad_se_deduplica_por_numero_y_contacto(self):
        primera = main._clave_registro_sheets(
            "2235550000", "+5492236000000", "Titular Uno", "30111222", "4 GB"
        )
        corregida = main._clave_registro_sheets(
            "223-555-0000", "2236000000", "Otro nombre", "40999888", "30 GB"
        )
        self.assertEqual(primera, corregida)

    def test_filtra_respuestas_en_ingles_aunque_no_parezcan_razonamiento(self):
        casos = [
            "Hello! How can I help you today?",
            "The customer has already sent the required data.",
            "Please send the front and back photos.",
            "Thanks!",
            "Great choice! Everything looks perfect.",
            "I can help you with that.",
            "perfecto, please mandame la otra foto",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertTrue(main._tiene_razonamiento_filtrado(texto))

    def test_no_bloquea_anglicismos_normales_dentro_del_espanol(self):
        casos = [
            "te paso el link de WhatsApp",
            "me falta tu email para completar los datos",
            "el plan incluye 30 GB de internet",
            "podés abrir la app de Claro?",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertFalse(main._tiene_razonamiento_filtrado(texto))

    def test_bloquea_repreguntar_compania_ya_informada(self):
        historial = [
            _mensaje(1, 0, "Hola, quiero pasarme a Claro"),
            _mensaje(2, 1, "de qué compañía sos?"),
            _mensaje(3, 0, "Movistar"),
            _mensaje(4, 1, "te paso los planes"),
            _mensaje(5, 0, "Hola, quiero pasarme a Claro"),
        ]
        motivo = main._motivo_respuesta_incoherente(
            "hola, soy Valentina. en qué compañía estás ahora?", historial
        )
        self.assertIn("volvió a preguntar", motivo)
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "hola de nuevo, te habían interesado estos planes?", historial
        ))
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "como ya sé cuál es tu compañía, seguimos con los planes de Movistar", historial
        ))
        variantes = [
            "con cuál compañía estás ahora?",
            "cuál es tu empresa actual?",
            "tu línea de qué compañía es?",
            "sos de Movistar, Personal o Tuenti?",
        ]
        for respuesta in variantes:
            with self.subTest(respuesta=respuesta):
                self.assertIsNotNone(
                    main._motivo_respuesta_incoherente(respuesta, historial)
                )

    def test_permite_preguntar_compania_de_una_segunda_linea(self):
        historial = [
            _mensaje(1, 0, "soy de Movistar"),
            _mensaje(2, 1, "cuál plan te interesa?"),
            _mensaje(3, 0, "también quiero agregar otra línea"),
        ]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "la otra línea de qué compañía es?", historial
        ))

    def test_responde_ubicacion_solo_con_mar_del_plata(self):
        historial = [
            _mensaje(1, 1, "en qué compañía estás?"),
            _mensaje(2, 0, "De donde son"),
        ]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "somos de Mar del Plata", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "trabajamos con Celtafone, agente oficial de Claro", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "trabajamos de forma online en todo el país", historial
        ))

    def test_responde_identidad_con_agentes_oficiales_de_claro(self):
        historial = [_mensaje(1, 0, "Quienes son ustedes?")]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "somos agentes oficiales de Claro", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "somos de Mar del Plata", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "somos Celtafone, agente oficial de Claro", historial
        ))

    def test_responde_juntas_ubicacion_e_identidad(self):
        historial = [_mensaje(1, 0, "¿De dónde son y quiénes son ustedes?")]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "somos de Mar del Plata y somos agentes oficiales de Claro", historial
        ))

    def test_bloquea_precio_empresa_sin_compania(self):
        historial = [_mensaje(1, 0, "la línea es de una empresa, con CUIT")]
        self.assertIn(
            "precio de Empresa",
            main._motivo_respuesta_incoherente(
                "por ejemplo el de 30gb te queda en $27.735", historial
            ),
        )
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "decime primero en qué compañía está la línea", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "el plan de 30gb queda en 27.735 pesos por mes", historial
        ))

    def test_bloquea_mezclar_precios_dni_de_personal_y_movistar(self):
        personal = [_mensaje(1, 0, "soy de Personal")]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "el de 30gb te queda en $34.680, con 70% off y 10gb de regalo", personal
        ))
        for respuesta in (
            "el de 30gb te queda en $40.460, con 65% off",
            "Personal tiene 65% de descuento",
        ):
            with self.subTest(respuesta=respuesta):
                self.assertIn(
                    "Movistar/Tuenti",
                    main._motivo_respuesta_incoherente(respuesta, personal),
                )

        movistar = [_mensaje(1, 0, "soy de Movistar")]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "el de 30gb te queda en $40.460, con 65% off y 10gb de regalo", movistar
        ))
        self.assertIn(
            "Personal",
            main._motivo_respuesta_incoherente(
                "el de 30gb te queda en $34.680, con 70% off", movistar
            ),
        )

    def test_bloquea_decir_que_personal_y_movistar_dni_valen_igual(self):
        historial = [_mensaje(1, 0, "tengo una línea Movistar y otra Personal")]
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "es lo mismo para las dos, tienen el mismo precio", historial
        ))
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "Movistar tiene 65% y Personal 70%; ambas mantienen los 10gb de regalo", historial
        ))

    def test_bloquea_afirmaciones_comerciales_no_verificadas(self):
        historial = [_mensaje(1, 0, "tengo una duda")]
        casos = [
            "los aumentos los va regulando el gobierno",
            "podés pedir que te cambien la fecha de vencimiento",
            "quedate tranquila, no es una estafa",
            "quedate tranquila que esto no es ninguna estafa",
            "es 100% seguro",
            "es totalmente seguro",
            "es el procedimiento oficial",
            "la foto es solo para validar los datos",
            "como no tenés deuda eso agiliza el cambio",
            "el roaming en Chile funciona como si estuvieras en Argentina, sin pagar extra",
            "tus contactos nunca se pierden, siempre quedan guardados",
            "en diciembre seguro te aumenta bastante",
            "si la das de baja perdés el número para siempre",
            "tus datos no se comparten con nadie más",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertIsNotNone(main._motivo_respuesta_incoherente(texto, historial))
        respuestas_seguras = [
            "no puedo confirmarte si se puede cambiar el vencimiento",
            "podés verificarlo por los medios oficiales de Claro antes de seguir",
            "trabajamos con Celtafone, agente oficial de Claro",
            "somos agentes oficiales de Claro",
            "los aumentos futuros los define la compañía y no puedo anticipar una fecha",
        ]
        for texto in respuestas_seguras:
            with self.subTest(texto=texto):
                self.assertIsNone(main._motivo_respuesta_incoherente(texto, historial))

    def test_bloquea_aceptar_un_email_invalido_en_el_turno_actual(self):
        historial = [
            _mensaje(1, 1, "pasame tu email"),
            _mensaje(2, 0, "arevalodavid@120.con"),
        ]
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "listo, lo anoto. ahora pasame tu localidad", historial
        ))
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "ese email parece tener un error, me lo revisás?", historial
        ))

    def test_normaliza_o_descarta_emails_antes_de_sheets(self):
        self.assertEqual(main._normalizar_email_ficha("juan@gmail.con"), "juan@gmail.com")
        self.assertEqual(main._normalizar_email_ficha("ventas@empresa.com.ar"), "ventas@empresa.com.ar")
        self.assertEqual(main._normalizar_email_ficha("arevalodavid@120.con"), "")
        campos = main._parse_ficha_fields("Nombre: Juan\nEmail: arevalodavid@120.con")
        self.assertNotIn("Email", campos)

    def test_un_pedido_visible_no_puede_cerrar_seguimientos(self):
        pendientes = [
            "dale, espero las fotos y con eso cerramos todo",
            "me falta el código postal",
            "cuando puedas mandame el dorso del DNI",
            "te sirve ese plan?",
        ]
        for texto in pendientes:
            with self.subTest(texto=texto):
                self.assertTrue(main._respuesta_deja_algo_pendiente(texto))
        self.assertFalse(main._respuesta_deja_algo_pendiente(
            "no hay problema, cualquier cosa me escribís. que andes bien"
        ))

    def test_detecta_reloj_de_followup_perdido_por_redeploy(self):
        ahora = 1_000_000
        last = _mensaje(
            9,
            1,
            "dale, espero las fotos",
            metadata=_metadata_bot(),
        )
        last["created_at"] = ahora - main.FOLLOWUP_DELAY_MIN_SECONDS - 60
        conversation = _conversacion_activa(
            id=92,
            last_non_activity_message=last,
        )
        # El mecanismo queda cubierto para una eventual reactivación, pero en producción está
        # forzado a apagado y por eso nunca selecciona candidatos por defecto.
        self.assertFalse(main._es_candidata_followup_recuperado(conversation, ahora))
        with patch.object(main, "FOLLOWUP_ENABLED", True):
            self.assertTrue(main._es_candidata_followup_recuperado(conversation, ahora))
        last["content_attributes"] = _metadata_bot(followup_closed=True)
        with patch.object(main, "FOLLOWUP_ENABLED", True):
            self.assertFalse(main._es_candidata_followup_recuperado(conversation, ahora))

    def test_no_habilita_seguimiento_por_audio_ilegible_o_pedido_de_tiempo(self):
        solo_audio = [
            _mensaje(1, 1, "el número que querés pasar, en qué compañía está?"),
            _mensaje(2, 0, attachments=[{"file_type": "audio", "extension": "ogg"}]),
            _mensaje(3, 1, "no puedo escuchar el audio, escribímelo por favor"),
        ]
        self.assertFalse(main._cliente_confirmo_plan(solo_audio))
        self.assertFalse(main._cliente_ya_paso_datos(solo_audio))

        pide_tiempo = [
            _mensaje(1, 1, "pasame nombre completo, DNI y número a portar"),
            _mensaje(2, 0, "me das un rato por favor"),
            _mensaje(3, 1, "dale, avisame cuando los tengas"),
        ]
        self.assertTrue(main._cliente_confirmo_plan(pide_tiempo))
        self.assertFalse(main._cliente_ya_paso_datos(pide_tiempo))

    def test_neutraliza_formulas_en_campos_de_sheets(self):
        self.assertEqual(main._valor_seguro_sheets("=IMPORTXML(A1)"), "'=IMPORTXML(A1)")
        self.assertEqual(main._valor_seguro_sheets("+5492230000000"), "'+5492230000000")
        self.assertEqual(main._valor_seguro_sheets("Mar del Plata"), "Mar del Plata")

    def test_imagenes_comerciales_previas_no_cuentan_como_dni(self):
        messages = [
            _mensaje(1, 0, "mirá mi factura", attachments=[_imagen("factura", 10)]),
            _mensaje(2, 1, "te paso los planes"),
            _mensaje(3, 0, "quiero el de 4gb"),
            _mensaje(4, 1, "pasame nombre completo, DNI y fotos frente y dorso"),
            _mensaje(5, 0, attachments=[_imagen("dni-frente", 11)]),
        ]
        candidatos = main._adjuntos_candidatos_dni(messages)
        self.assertEqual([item["_dni_url"] for item in candidatos], ["dni-frente"])

    def test_reclamos_de_chip_anterior_son_postventa_y_no_ventas(self):
        hugo = [
            _mensaje(1, 0, "el viernes le pasé todas las fotos del documento a la chica"),
            _mensaje(2, 1, "mandame frente y dorso del DNI"),
            _mensaje(3, 0, attachments=[_imagen("frente", 10), _imagen("dorso", 20)]),
        ]
        gabriela = [
            _mensaje(1, 0, "hola, habrá llegado mi chip? lo espero desde la semana pasada"),
            _mensaje(2, 1, "mandame frente y dorso del DNI"),
            _mensaje(3, 0, attachments=[_imagen("frente", 10), _imagen("dorso", 20)]),
        ]
        preventa = [
            _mensaje(1, 0, "cuánto demora en llegar el chip si hago el cambio?"),
        ]
        variantes_postventa = (
            "nunca me llegó el chip",
            "ya tengo el chip pero no funciona",
            "quiero activar la sim que recibí",
            "ya le pasé todos los datos y las fotos del DNI",
        )
        self.assertTrue(main._es_contexto_postventa(hugo))
        self.assertTrue(main._es_contexto_postventa(gabriela))
        for texto in variantes_postventa:
            self.assertTrue(main._es_contexto_postventa([_mensaje(1, 0, texto)]), texto)
        self.assertFalse(main._es_contexto_postventa(preventa))
        self.assertFalse(main._es_candidata_a_recuperar(hugo))
        self.assertFalse(main._es_candidata_a_recuperar(gabriela))

    def test_una_ficha_con_solo_nombre_y_fotos_no_es_valida(self):
        faltantes = main._campos_faltantes_derivacion({
            "Tipo de cliente": "Consumidor final",
            "Nombre": "Hugo",
        })
        self.assertIn("tipo de portabilidad", faltantes)
        self.assertIn("nombre completo del titular", faltantes)
        self.assertIn("plan elegido", faltantes)

    def test_ficha_consumidor_completa_supera_validacion_comercial(self):
        self.assertEqual(
            main._campos_faltantes_derivacion(self._ficha_consumidor_completa()),
            [],
        )

    def test_empresa_exige_cuit_valido_y_categoria_fiscal(self):
        campos = {
            **self._ficha_consumidor_completa(),
            "Tipo de cliente": "Empresa",
            "CUIT": "27-30519335-1",
        }
        confirmo_categoria = [
            _mensaje(1, 0, "soy monotributista social, mi CUIT es 27-30519335-1"),
        ]
        self.assertTrue(main._cuit_formato_valido(campos["CUIT"]))
        self.assertEqual(main._campos_faltantes_derivacion(campos, confirmo_categoria), [])

    def test_empresa_rechaza_cuit_sin_categoria_fiscal_admitida(self):
        campos = {
            **self._ficha_consumidor_completa(),
            "Tipo de cliente": "Empresa",
            "CUIT": "27-30519335-1",
        }
        messages = [
            _mensaje(1, 0, "lo quiero hacer con CUIT"),
        ]
        self.assertIn(
            "confirmación de que es monotributista o responsable inscripto",
            main._campos_faltantes_derivacion(campos, messages),
        )

    def test_empresa_no_acepta_un_cuit_que_el_cliente_nunca_escribio(self):
        campos = {
            **self._ficha_consumidor_completa(),
            "Tipo de cliente": "Empresa",
            "CUIT": "27-30519335-1",
        }
        messages = [_mensaje(1, 0, "soy responsable inscripto")]
        self.assertIn(
            "CUIT del titular informado por el cliente",
            main._campos_faltantes_derivacion(campos, messages),
        )

    def test_no_confunde_negacion_con_categoria_empresa(self):
        for respuesta in (
            "no soy monotributista",
            "antes era responsable inscripto",
            "no sé si soy monotributista",
            "y cuánto sale para monotributista?",
            "qué planes tienen para responsable inscripta?",
            "precio monotributista",
        ):
            messages = [_mensaje(1, 0, respuesta)]
            self.assertFalse(main._cliente_confirmo_condicion_empresa(messages), respuesta)

    def test_reconoce_variantes_validas_de_categoria_empresa(self):
        for respuesta in (
            "soy monotributista",
            "tengo monotributo social",
            "soy responsable inscripta",
            "soy RI",
            "monotributista",
        ):
            messages = [_mensaje(1, 0, respuesta)]
            self.assertTrue(main._cliente_confirmo_condicion_empresa(messages), respuesta)

    def test_negacion_de_empresa_no_bloquea_precio_consumidor_final(self):
        messages = [
            _mensaje(1, 0, "soy de Movistar"),
            _mensaje(2, 0, "no soy monotributista, es con DNI"),
        ]
        self.assertFalse(main._cliente_planteo_empresa(messages))
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "el de 4gb te queda en $20.997, ya con el 65% off aplicado",
            messages,
        ))

    def test_mensaje_de_bloqueo_pide_solo_categoria_fiscal(self):
        mensaje = main._mensaje_ficha_incompleta([
            "confirmación de que es monotributista o responsable inscripto",
        ])
        self.assertIn("monotributista o responsable inscripto", mensaje)
        self.assertNotIn("activo", mensaje.lower())

    def test_prompt_no_pide_confirmar_estado_del_cuit(self):
        self.assertNotIn("¿tenés el CUIT activo", main.SYSTEM_PROMPT)
        self.assertNotIn("CUIT activo declarado", main.SYSTEM_PROMPT)
        self.assertNotIn("CUIT_ACTIVO_CONFIRMADO", main.SYSTEM_PROMPT)

    def test_bloquea_garantia_no_verificada_sobre_cuit(self):
        historial = [
            _mensaje(1, 0, "soy monotributista"),
            _mensaje(2, 0, "me dijeron que no se puede pasar de DNI a CUIT"),
        ]
        motivo = main._motivo_respuesta_incoherente(
            "lo que te dijeron no es correcto, se puede hacer sin ningún problema con CUIT",
            historial,
        )
        self.assertIsNotNone(motivo)


class ProteccionesAsincronicasTest(unittest.IsolatedAsyncioTestCase):
    async def test_append_confirma_fila_antes_de_reintentar_o_alertar(self):
        row = [""] * 26
        row[8] = "Cecilia Sangon de los Angeles"
        row[9] = "35667227"
        row[23] = "3515583661"
        row[24] = "+5493515583661"
        row[25] = "50 GB"

        cliente = AsyncMock()
        cliente.post.side_effect = TimeoutError("la respuesta llegó tarde")
        contexto = AsyncMock()
        contexto.__aenter__.return_value = cliente
        confirmar = AsyncMock(return_value="Hoja 1!A193:Z193")
        avisar = AsyncMock()

        with (
            patch.object(main, "GOOGLE_SHEETS_CREDENTIALS_JSON", "{}"),
            patch.object(main, "GOOGLE_SHEETS_SPREADSHEET_ID", "planilla"),
            patch.object(main, "_get_sheets_access_token", AsyncMock(return_value="token")),
            patch.object(main.httpx, "AsyncClient", return_value=contexto),
            patch.object(main, "_confirmar_fila_sheets_despues_de_error", confirmar),
            patch.object(main, "_avisar_error_sheets", avisar),
        ):
            resultado = await main.append_google_sheets_row(row)

        self.assertEqual(resultado, "Hoja 1!A193:Z193")
        self.assertEqual(cliente.post.await_count, 1)
        confirmar.assert_awaited_once_with(row, "token")
        avisar.assert_not_awaited()

    async def test_update_confirma_cambios_antes_de_reintentar_o_alertar(self):
        existente = [""] * 26
        existente[8] = "Cecilia Sangon de los Angeles"
        # La API real de Sheets entrega estas celdas como números con valueRenderOption=FORMULA.
        existente[9] = 35667227
        existente[12] = "Pendiente con Camila"
        existente[23] = 3515583661
        existente[24] = "+5493515583661"
        existente[25] = "50 GB"
        nueva = existente.copy()
        nueva[12] = '=HYPERLINK("foto";"Ver foto DNI")'

        respuesta_get = MagicMock()
        respuesta_get.json.return_value = {"values": [[""] * 26, existente]}
        cliente = AsyncMock()
        cliente.get.return_value = respuesta_get
        cliente.post.side_effect = TimeoutError("la respuesta llegó tarde")
        contexto = AsyncMock()
        contexto.__aenter__.return_value = cliente
        confirmar = AsyncMock(return_value=True)
        avisar = AsyncMock()

        with (
            patch.object(main, "_get_sheets_access_token", AsyncMock(return_value="token")),
            patch.object(main.httpx, "AsyncClient", return_value=contexto),
            patch.object(main, "_confirmar_cambios_fila_sheets", confirmar),
            patch.object(main, "_forzar_links_visibles", AsyncMock()),
            patch.object(main, "_avisar_error_sheets", avisar),
        ):
            resultado = await main._actualizar_fila_existente(
                "3515583661", "+5493515583661", nueva
            )

        self.assertTrue(resultado)
        self.assertEqual(cliente.post.await_count, 1)
        confirmar.assert_awaited_once()
        avisar.assert_not_awaited()

    async def test_no_duplica_el_mismo_aviso_de_sheets(self):
        main._errores_sheets_avisados.clear()
        row = [""] * 26
        row[8] = "Cecilia Sangon de los Angeles"
        row[23] = "3515583661"
        row[24] = "+5493515583661"
        send = AsyncMock()

        with (
            patch.object(main, "NUMERO_DUENO", "5492200000000"),
            patch.object(main, "_find_conversation_by_phone", AsyncMock(return_value=10)),
            patch.object(main, "send_message", send),
        ):
            await main._avisar_error_sheets(row)
            await main._avisar_error_sheets(row)

        send.assert_awaited_once()
        main._errores_sheets_avisados.clear()

    async def test_no_duplica_el_mismo_aviso_de_falla_en_una_hora(self):
        main._fallos_respuesta_avisados.clear()
        send = AsyncMock()
        with (
            patch.object(main, "NUMERO_DUENO", "+5490000000000"),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5491111111111")),
            patch.object(main, "_find_conversation_by_phone", AsyncMock(return_value=99)),
            patch.object(main, "send_message", send),
        ):
            await main._avisar_fallo_respuesta(80, "mismo error")
            await main._avisar_fallo_respuesta(80, "mismo error")
        send.assert_awaited_once()
        main._fallos_respuesta_avisados.clear()

    async def test_openrouter_reintenta_si_devuelve_solo_espacios(self):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = [
            {"choices": [{"message": {"content": "  \n  "}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": "respuesta válida"}, "finish_reason": "stop"}]},
        ]
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(main.httpx, "AsyncClient", return_value=context):
            respuesta = await main.call_openrouter(
                [{"role": "user", "content": "hola"}], intentos=2
            )
        self.assertEqual(respuesta, "respuesta válida")
        self.assertEqual(client.post.await_count, 2)
        for llamada in client.post.await_args_list:
            self.assertEqual(
                llamada.kwargs["json"]["max_tokens"],
                main.OPENROUTER_MAX_TOKENS,
            )
            self.assertTrue(llamada.kwargs["json"]["reasoning"]["exclude"])

    async def test_openrouter_no_reintenta_contenido_bloqueado(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "error": {"code": "PROHIBITED_CONTENT", "message": "blocked by safety policy"}
        }
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(main.httpx, "AsyncClient", return_value=context):
            with self.assertRaises(main.OpenRouterContenidoBloqueadoError):
                await main.call_openrouter([{"role": "user", "content": "imagen"}], intentos=3)
        self.assertEqual(client.post.await_count, 1)

    async def test_regenera_una_respuesta_comercial_incoherente(self):
        historial = [_mensaje(1, 0, "soy de Movistar")]
        with patch.object(
            main,
            "call_openrouter",
            AsyncMock(side_effect=[
                "hola, en qué compañía estás?",
                "seguimos con Movistar, cuál plan te interesa?",
            ]),
        ) as openrouter:
            respuesta = await main._call_openrouter_respuesta_cliente(
                [{"role": "system", "content": "prueba"}], historial
            )
        self.assertEqual(respuesta, "seguimos con Movistar, cuál plan te interesa?")
        self.assertEqual(openrouter.await_count, 2)

    async def test_mensaje_normal_del_bot_lleva_marca_interna(self):
        client = AsyncMock()
        response = MagicMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(main.httpx, "AsyncClient", return_value=context):
            await main.send_message(10, "respuesta normal")
        body = client.post.await_args.kwargs["json"]
        self.assertEqual(
            body["content_attributes"]["data"][main.FOLLOWUP_METADATA_KEY]["kind"],
            "bot_reply",
        )

    async def test_registro_sin_fotos_deriva_y_marca_pendientes(self):
        sheets = AsyncMock(return_value=True)
        notify = AsyncMock()
        label = AsyncMock(return_value=True)
        with (
            patch.object(main, "_verificar_fotos_dni", AsyncMock(return_value=("", ""))),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5492200000000")),
            patch.object(main, "log_to_google_sheets", sheets),
            patch.object(main, "notify_camila_carga_sheets", notify),
            patch.object(main, "add_conversation_label", label),
        ):
            await main._registrar_derivacion_completa(
                12,
                _ficha_consumidor_completa(),
                [],
            )
        self.assertTrue(sheets.await_args.kwargs["foto_dni_pendiente"])
        self.assertTrue(notify.await_args.kwargs["foto_dni_pendiente"])
        label.assert_awaited_once_with(12, main.DERIVADO_LABEL)

    async def test_registro_con_negativa_explicita_deja_foto_pendiente(self):
        mensajes = [
            _mensaje(1, 1, "para cerrar mandame foto del frente y dorso del DNI"),
            _mensaje(2, 0, "no lo tengo a mano, se las paso a Camila"),
        ]
        sheets = AsyncMock(return_value=True)
        notify = AsyncMock()
        label = AsyncMock(return_value=True)
        with (
            patch.object(main, "_verificar_fotos_dni", AsyncMock(return_value=("", ""))),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5492200000000")),
            patch.object(main, "log_to_google_sheets", sheets),
            patch.object(main, "notify_camila_carga_sheets", notify),
            patch.object(main, "add_conversation_label", label),
        ):
            await main._registrar_derivacion_completa(
                12,
                {**_ficha_consumidor_completa(), "Fecha de nacimiento": "01/01/1990"},
                mensajes,
            )

        self.assertEqual(sheets.await_args.args[2], "")
        self.assertEqual(sheets.await_args.args[3:5], ("", ""))
        self.assertTrue(sheets.await_args.kwargs["foto_dni_pendiente"])
        self.assertTrue(notify.await_args.kwargs["foto_dni_pendiente"])
        label.assert_awaited_once_with(12, main.DERIVADO_LABEL)

    async def test_sheets_marca_ambas_fotos_pendientes_con_camila(self):
        append = AsyncMock(return_value="Hoja 1!A10:Z10")
        with (
            patch.object(main, "GOOGLE_SHEETS_CREDENTIALS_JSON", "{}"),
            patch.object(main, "GOOGLE_SHEETS_SPREADSHEET_ID", "planilla"),
            patch.object(main, "_pares_numero_telefono_existentes", AsyncMock(return_value=set())),
            patch.object(main, "append_google_sheets_row", append),
            patch.object(main, "_forzar_links_visibles", AsyncMock()),
        ):
            ok = await main.log_to_google_sheets(
                _ficha_consumidor_completa(),
                "+5492200000000",
                foto_dni_pendiente=True,
            )
        self.assertTrue(ok)
        row = append.await_args.args[0]
        self.assertEqual(row[2:6], ["", "", "", ""])
        self.assertRegex(row[6], r"^'\d{2}:\d{2}$")
        self.assertRegex(row[7], r"^\d{2}/\d{2}/\d{4}$")
        self.assertEqual(row[8], "Ana María Pérez")
        self.assertEqual(row[12], "Pendiente con Camila")
        self.assertEqual(row[13], "Pendiente con Camila")
        self.assertEqual(row[15:20], [
            "Movistar", "Consumidor final", "Buenos Aires", "Mar del Plata",
            "San Martín 1234",
        ])
        self.assertEqual(row[22:26], [
            "7600", "2235551234", "'+5492200000000", "4 GB",
        ])
        self.assertEqual(len(row), 26)

    async def test_sheets_agrega_segunda_linea_nueva_de_otro_titular_mismo_contacto(self):
        telefono = "+5493624030510"
        clave_veronica = main._clave_registro_sheets(
            "LÍNEA NUEVA", telefono, "Piriz Verónica Vanesa", "31142619", "2 GB"
        )
        ficha_norma = {
            "Tipo de portabilidad": "Línea nueva",
            "Tipo de cliente": "Consumidor final",
            "Nombre": "Cabrera Norma Graciela",
            "DNI": "23273999",
            "Plan elegido": "30 GB",
            "Localidad": "Puerto Vilelas",
            "Provincia": "Chaco",
            "Dirección": "Barrio Independencia Mz. 31 Pc. 28",
            "Código postal": "3503",
        }
        append = AsyncMock(return_value="Hoja 1!A10:Z10")
        actualizar = AsyncMock(return_value=True)
        with (
            patch.object(main, "GOOGLE_SHEETS_CREDENTIALS_JSON", "{}"),
            patch.object(main, "GOOGLE_SHEETS_SPREADSHEET_ID", "planilla"),
            patch.object(main, "_pares_numero_telefono_existentes",
                         AsyncMock(return_value={clave_veronica})),
            patch.object(main, "append_google_sheets_row", append),
            patch.object(main, "_actualizar_fila_existente", actualizar),
            patch.object(main, "_forzar_links_visibles", AsyncMock()),
        ):
            ok = await main.log_to_google_sheets(ficha_norma, telefono)
        self.assertTrue(ok)
        append.assert_awaited_once()
        actualizar.assert_not_awaited()

    async def test_fotos_posteriores_actualizan_todas_las_filas_sin_agregar_ventas(self):
        encabezado = [""] * 26
        fila_1 = [""] * 26
        fila_2 = [""] * 26
        fila_1[12] = fila_1[13] = "Pendiente con Camila"
        fila_2[12] = fila_2[13] = "Pendiente con Camila"
        fila_1[24] = fila_2[24] = "+5492200000000"

        respuesta_get = MagicMock()
        respuesta_get.json.return_value = {"values": [encabezado, fila_1, fila_2]}
        respuesta_post = MagicMock()
        cliente = AsyncMock()
        cliente.get.return_value = respuesta_get
        cliente.post.return_value = respuesta_post
        contexto = AsyncMock()
        contexto.__aenter__.return_value = cliente
        forzar = AsyncMock()

        with (
            patch.object(main, "GOOGLE_SHEETS_CREDENTIALS_JSON", "{}"),
            patch.object(main, "GOOGLE_SHEETS_SPREADSHEET_ID", "planilla"),
            patch.object(main, "_get_sheets_access_token", AsyncMock(return_value="token")),
            patch.object(main.httpx, "AsyncClient", return_value=contexto),
            patch.object(main, "_forzar_links_visibles", forzar),
        ):
            filas, cambios = await main._actualizar_fotos_dni_pendientes(
                "+5492200000000", "foto-frente", "foto-dorso"
            )

        self.assertEqual((filas, cambios), (2, 4))
        rangos = [item["range"] for item in cliente.post.await_args.kwargs["json"]["data"]]
        self.assertEqual(rangos, ["Hoja 1!M2", "Hoja 1!N2", "Hoja 1!M3", "Hoja 1!N3"])
        self.assertEqual(forzar.await_count, 2)

    async def test_registro_con_una_cara_conserva_la_foto_recibida(self):
        mensajes = [
            _mensaje(1, 1, "mandame foto del frente y dorso del DNI"),
            _mensaje(2, 0, attachments=[_imagen("dni-frente", 101)]),
            _mensaje(3, 0, "el dorso te lo mando después a Camila"),
        ]
        sheets = AsyncMock(return_value=True)
        with (
            patch.object(main, "_verificar_fotos_dni",
                         AsyncMock(return_value=("dni-frente", ""))),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5492200000000")),
            patch.object(main, "log_to_google_sheets", sheets),
            patch.object(main, "notify_camila_carga_sheets", AsyncMock()),
            patch.object(main, "add_conversation_label", AsyncMock(return_value=True)),
        ):
            await main._registrar_derivacion_completa(
                12,
                _ficha_consumidor_completa(),
                mensajes,
            )
        self.assertEqual(sheets.await_args.args[3:5], ("dni-frente", ""))
        self.assertTrue(sheets.await_args.kwargs["foto_dni_pendiente"])

    async def test_postventa_no_se_registra_aunque_tenga_fotos(self):
        mensajes = [
            _mensaje(1, 0, "habrá llegado mi chip? lo espero desde la semana pasada"),
            _mensaje(2, 0, attachments=[
                _imagen("dni-frente", 101),
                _imagen("dni-dorso", 102),
            ]),
        ]
        sheets = AsyncMock()
        label = AsyncMock()
        with (
            patch.object(main, "log_to_google_sheets", sheets),
            patch.object(main, "add_conversation_label", label),
        ):
            with self.assertRaises(main.DerivacionPostventaError):
                await main._registrar_derivacion_completa(
                    12,
                    _ficha_consumidor_completa(),
                    mensajes,
                )
        sheets.assert_not_awaited()
        label.assert_not_awaited()

    async def test_falla_de_sheets_no_avisa_a_camila_ni_etiqueta_ddd(self):
        notify = AsyncMock()
        label = AsyncMock()
        with (
            patch.object(main, "_verificar_fotos_dni",
                         AsyncMock(return_value=("frente", "dorso"))),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5492200000000")),
            patch.object(main, "log_to_google_sheets", AsyncMock(return_value=False)),
            patch.object(main, "notify_camila_carga_sheets", notify),
            patch.object(main, "add_conversation_label", label),
        ):
            with self.assertRaisesRegex(RuntimeError, "Google Sheets"):
                await main._registrar_derivacion_completa(
                    12,
                    _ficha_consumidor_completa(),
                    [],
                )
        notify.assert_not_awaited()
        label.assert_not_awaited()

    async def test_verifica_dos_caras_y_acepta_dni_digital_en_un_adjunto(self):
        mensajes_dos = [
            _mensaje(1, 1, "pasame foto del frente y dorso del DNI"),
            _mensaje(2, 0, attachments=[
                _imagen("dni-frente-unico", 101),
                _imagen("dni-dorso-unico", 102),
            ]),
        ]
        main._dni_verification_cache.clear()
        with (
            patch.object(main, "download_attachment",
                         AsyncMock(return_value=(b"imagen", "image/jpeg"))),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="COMPLETO FRENTE=1 DORSO=2")),
        ):
            self.assertEqual(
                await main._verificar_fotos_dni(mensajes_dos),
                ("dni-frente-unico", "dni-dorso-unico"),
            )

        mensajes_digital = [
            _mensaje(1, 1, "pasame una foto del DNI"),
            _mensaje(2, 0, "DNI digital de Mi Argentina",
                     attachments=[_imagen("dni-digital-ambas", 103)]),
        ]
        main._dni_verification_cache.clear()
        with (
            patch.object(main, "download_attachment",
                         AsyncMock(return_value=(b"imagen", "image/jpeg"))),
            patch.object(main, "call_openrouter", AsyncMock(return_value="COMPLETO AMBAS=1")),
        ):
            self.assertEqual(
                await main._verificar_fotos_dni(mensajes_digital),
                ("dni-digital-ambas", "dni-digital-ambas"),
            )

    async def test_verifica_una_sola_cara_sin_descartarla(self):
        mensajes = [
            _mensaje(1, 1, "si querés mandame las fotos del DNI"),
            _mensaje(2, 0, attachments=[_imagen("dni-dorso", 104)]),
        ]
        main._dni_verification_cache.clear()
        with (
            patch.object(main, "download_attachment",
                         AsyncMock(return_value=(b"imagen", "image/jpeg"))),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="PARCIAL DORSO=1")),
        ):
            self.assertEqual(
                await main._verificar_fotos_dni(mensajes),
                ("", "dni-dorso"),
            )

    async def test_build_message_content_entrega_todos_los_adjuntos_al_modelo(self):
        mensaje = _mensaje(1, 0, "frente y dorso", attachments=[
            _imagen("frente-lote", 201),
            _imagen("dorso-lote", 202),
        ])
        with patch.object(
            main,
            "build_image_content",
            AsyncMock(side_effect=[
                [{"type": "image_url", "image_url": {"url": "frente"}}],
                [{"type": "image_url", "image_url": {"url": "dorso"}}],
            ]),
        ) as build:
            contenido, tipo = await main.build_message_content(mensaje)
        self.assertEqual(build.await_count, 2)
        self.assertEqual(tipo, "documents")
        self.assertEqual(len(contenido), 2)

    async def test_no_encadena_seguimiento_sobre_otro_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "te quedó alguna duda?", metadata=_metadata_seguimiento(1)),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_no_sigue_si_la_ultima_respuesta_cerro_followups(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "gracias, que andes bien", metadata=_metadata_bot(True)),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_envia_primero_y_segundo_con_secuencia_persistente(self):
        base = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta el código postal", metadata=_metadata_bot()),
        ]
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=base)),
            patch.object(main, "call_openrouter", AsyncMock(return_value="me pasás el código postal?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        metadata_1 = send.await_args.kwargs["content_attributes"]
        self.assertEqual(
            metadata_1["data"][main.FOLLOWUP_METADATA_KEY]["sequence"], 1
        )

        con_primero_y_respuesta = base + [
            _mensaje(4, 1, "seguimiento uno", metadata=_metadata_seguimiento(1)),
            _mensaje(5, 0, "2000"),
            _mensaje(6, 1, "ahora me falta la foto del DNI", metadata=_metadata_bot()),
        ]
        send.reset_mock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages",
                         AsyncMock(return_value=con_primero_y_respuesta)),
            patch.object(main, "call_openrouter", AsyncMock(return_value="me mandás las fotos?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        metadata_2 = send.await_args.kwargs["content_attributes"]
        self.assertEqual(
            metadata_2["data"][main.FOLLOWUP_METADATA_KEY]["sequence"], 2
        )

    async def test_bloquea_un_tercer_seguimiento_aunque_el_cliente_haya_respondido(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "seguimiento uno", metadata=_metadata_seguimiento(1)),
            _mensaje(4, 0, "Córdoba 123"),
            _mensaje(5, 1, "seguimiento dos", metadata=_metadata_seguimiento(2)),
            _mensaje(6, 0, "mi código postal es 2000"),
            _mensaje(7, 1, "perfecto, me falta el DNI", metadata=_metadata_bot()),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_no_sigue_despues_de_un_mensaje_manual(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "hola, tomo yo la conversación"),  # sin metadato = humano
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_no_sigue_una_conversacion_resuelta(self):
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa(status="resolved"))),
            patch.object(main, "_fetch_conversation_messages", AsyncMock()) as fetch,
        ):
            await main.send_followup_if_needed(10, 2700)
        fetch.assert_not_awaited()

    async def test_no_sigue_si_chatwoot_no_permite_responder(self):
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa(can_reply=False))),
            patch.object(main, "_fetch_conversation_messages", AsyncMock()) as fetch,
        ):
            await main.send_followup_if_needed(10, 2700)
        fetch.assert_not_awaited()

    async def test_no_sigue_si_el_cliente_ya_respondio(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
            _mensaje(4, 0, "calle Córdoba 123"),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_varias_burbujas_se_envian_como_un_solo_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="me pasás la calle?\n---\ny la altura?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1], "me pasás la calle?\n\ny la altura?")

    async def test_reintenta_envio_de_seguimiento_sin_duplicar(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        send = AsyncMock(side_effect=[RuntimeError("timeout"), None])
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages",
                         AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="me pasás la dirección?")),
            patch.object(main, "send_message", send),
            patch.object(main.asyncio, "sleep", AsyncMock()),
            patch.object(main, "_avisar_fallo_respuesta", AsyncMock()) as aviso,
        ):
            await main.send_followup_if_needed(10, 2700)
        self.assertEqual(send.await_count, 2)
        aviso.assert_not_awaited()

    async def test_no_permite_derivar_desde_un_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        respuesta_mala = f"escribile a Camila: {main.NUMERO_CAMILA}"
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock(return_value=respuesta_mala)) as openrouter,
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        self.assertEqual(openrouter.await_count, 2)
        send.assert_not_awaited()

    async def test_cancela_si_un_humano_responde_mientras_se_redacta(self):
        antes = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        despues = antes + [_mensaje(4, 1, "hola, sigo yo desde acá")]
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages",
                         AsyncMock(side_effect=[antes, despues])),
            patch.object(main, "call_openrouter", AsyncMock(return_value="me pasás la calle?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        send.assert_not_awaited()


class MetaLeadFormTest(unittest.TestCase):
    def _headers(self):
        return main._META_LEADFORM_HEADERS + [
            "id", "created_time", "ad_id", "ad_name", "adset_id", "adset_name",
            "campaign_id", "campaign_name", "form_id", "form_name", "is_organic",
            "platform", "¿qué_compañía_de_celular_tenés_actualmente?",
            "estos_son_los_planes_que_tenemos_con_un_70%_de_descuento!",
            "estos_son_los_planes_que_tenemos_con_descuento!", "nombre_y_apellidos",
            "correo_electrónico", "número_de_teléfono", "provincia", "ciudad",
            "dirección_postal", "dni_(argentina)", "lead_status",
            "estos_son_los_planes_que_tenemos_con_descuento_para_vos:",
            "estos_son_los_planes_que_tenemos_con_descuento:", "código_postal",
            "¿qué_tipo_de_línea_tenés?",
        ]

    def _raw_row(self):
        row = [""] * main._META_LEADFORM_TOTAL_COLUMN_COUNT
        row[:22] = [
            "l:1766603177946012", "2026-10-18T20:26:58-05:00", "", "", "", "", "", "",
            "f:1429855975231545", "Form", "true", "", "Movistar", "Plan 4 GB", "",
            "Franco Pérez", "franco@example.com", "p:+5492236000000", "Buenos Aires",
            "Mar del Plata", "San Martín 1234", "12345678",
        ]
        row[50] = "CREATED"
        return row

    def test_ordena_fila_meta_y_conserva_datos_tecnicos(self):
        ordered = main._ordenar_fila_leadform_meta(self._headers(), self._raw_row())
        self.assertIsNotNone(ordered)
        self.assertEqual(ordered[6], "22:26")
        self.assertEqual(ordered[7], "18/10/2026")
        self.assertEqual(ordered[8], "")
        self.assertEqual(ordered[9], "Franco Pérez")
        self.assertEqual(ordered[10], "12345678")
        self.assertEqual(ordered[15], "franco@example.com")
        self.assertEqual(ordered[16], "Movistar")
        self.assertEqual(ordered[17], "")
        self.assertEqual(ordered[18], "Consumidor final")
        self.assertEqual(ordered[19], "Buenos Aires")
        self.assertEqual(ordered[20], "Mar del Plata")
        self.assertEqual(ordered[21], "San Martín 1234")
        self.assertEqual(ordered[25], "'+5492236000000")
        self.assertEqual(ordered[26], "'+5492236000000")
        self.assertEqual(ordered[27], "Plan 4 GB")
        self.assertEqual(ordered[28], "l:1766603177946012")
        self.assertEqual(ordered[41], "Plan 4 GB")
        self.assertEqual(ordered[42], "")
        self.assertEqual(ordered[49], "12345678")
        self.assertEqual(ordered[50], "CREATED")
        self.assertEqual(ordered[51], "")
        self.assertEqual(ordered[53], "")
        self.assertEqual(ordered[54], "")

    def test_no_reprocesa_una_fila_ya_ordenada(self):
        ordered = main._ordenar_fila_leadform_meta(self._headers(), self._raw_row())
        self.assertIsNone(main._ordenar_fila_leadform_meta(self._headers(), ordered))

    def test_formulario_nuevo_distingue_codigo_postal_direccion_y_dni(self):
        row = self._raw_row()
        row[13] = "14gb_→_$20.997"
        row[20] = "z:8332"
        row[21] = "Calle Israel 1764"
        row[22] = "30123456"
        ordered = main._ordenar_fila_leadform_meta(self._headers(), row)
        self.assertEqual(ordered[10], "30123456")
        self.assertEqual(ordered[21], "Calle Israel 1764")
        self.assertEqual(ordered[24], "8332")
        self.assertEqual(ordered[27], "14 GB → $20.997")
        self.assertEqual(ordered[41], "")
        self.assertEqual(ordered[42], "")
        self.assertEqual(ordered[49], "30123456")
        self.assertEqual(ordered[50], "CREATED")
        self.assertEqual(ordered[51], "14gb_→_$20.997")
        self.assertEqual(ordered[52], "")
        self.assertEqual(ordered[53], "z:8332")
        self.assertEqual(ordered[54], "")

    def test_formulario_de_un_plan_no_desplaza_los_datos(self):
        row = [""] * main._META_LEADFORM_TOTAL_COLUMN_COUNT
        row[:22] = [
            "l:28723009143976254", "2026-10-20T10:17:27-05:00", "", "", "", "",
            "", "", "f:1130760232740855", "Leadform 1-copy", "false", "ig",
            "personal", "40gb_→_$40.460", "Juan Ignacio Flores",
            "juanflores@example.com", "p:+5493364341110", "Buenos Aires",
            "San Nicolás de los Arroyos, Buenos Aires", "z:2900",
            "Calle Leon Guruciaga 1104", "29362167",
        ]
        row[50] = "CREATED"

        ordered = main._ordenar_fila_leadform_meta(self._headers(), row)

        self.assertEqual(ordered[9], "Juan Ignacio Flores")
        self.assertEqual(ordered[10], "29362167")
        self.assertEqual(ordered[15], "juanflores@example.com")
        self.assertEqual(ordered[16], "personal")
        self.assertEqual(ordered[17], "")
        self.assertEqual(ordered[19], "Buenos Aires")
        self.assertEqual(ordered[20], "San Nicolás de los Arroyos, Buenos Aires")
        self.assertEqual(ordered[21], "Calle Leon Guruciaga 1104")
        self.assertEqual(ordered[24], "2900")
        self.assertEqual(ordered[25], "'+5493364341110")
        self.assertEqual(ordered[26], "'+5493364341110")
        self.assertEqual(ordered[27], "40 GB → $40.460")
        self.assertEqual(ordered[43], "Juan Ignacio Flores")
        self.assertEqual(ordered[49], "29362167")
        self.assertEqual(ordered[51], "")
        self.assertEqual(ordered[52], "40gb_→_$40.460")
        self.assertEqual(ordered[53], "z:2900")
        self.assertEqual(ordered[54], "")

    def test_formulario_con_tipo_de_linea(self):
        row = [""] * main._META_LEADFORM_TOTAL_COLUMN_COUNT
        row[:23] = [
            "l:1102533235725521", "2026-10-21T18:13:38-05:00", "", "", "", "",
            "", "", "f:1156836676699206", "DEFINITIVO ALL INFO", "true", "fb",
            "movistar", "14gb_→_$17.997", "no_sé", "Pedro Gómez",
            "pedro@example.com", "p:+5492236000001", "Buenos Aires", "Mar del Plata",
            "z:7600", "San Martín 123", "30111222",
        ]
        row[50] = "CONTACTED"

        ordered = main._ordenar_fila_leadform_meta(self._headers(), row)

        self.assertEqual(ordered[9], "Pedro Gómez")
        self.assertEqual(ordered[10], "30111222")
        self.assertEqual(ordered[16], "movistar")
        self.assertEqual(ordered[17], "No sé")
        self.assertEqual(ordered[18], "Consumidor final")
        self.assertEqual(ordered[19], "Buenos Aires")
        self.assertEqual(ordered[20], "Mar del Plata")
        self.assertEqual(ordered[21], "San Martín 123")
        self.assertEqual(ordered[24], "7600")
        self.assertEqual(ordered[27], "14 GB → $17.997")
        self.assertEqual(ordered[50], "CONTACTED")
        self.assertEqual(ordered[51], "14gb_→_$17.997")
        self.assertEqual(ordered[52], "")
        self.assertEqual(ordered[53], "z:7600")
        self.assertEqual(ordered[54], "no_sé")

    def test_rechaza_otra_estructura_de_hoja(self):
        headers = self._headers()
        headers[0] = "OTRA HOJA"
        self.assertIsNone(main._ordenar_fila_leadform_meta(headers, self._raw_row()))


if __name__ == "__main__":
    unittest.main()
