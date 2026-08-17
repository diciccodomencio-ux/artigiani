import unittest
from types import SimpleNamespace

import app.routes as routes


class MetaWebhookResponseTests(unittest.TestCase):
    def test_meta_inbound_returns_200_and_uses_meta_api(self):
        calls = []

        original_get_customer_by_phone = routes.crud.get_customer_by_phone
        original_create_customer = routes.crud.create_customer
        original_get_conversation_by_customer_channel = routes.crud.get_conversation_by_customer_channel
        original_create_conversation = routes.crud.create_conversation
        original_create_message = routes.crud.create_message
        original_get_service_request = routes.crud.get_service_request
        original_create_service_request = routes.crud.create_service_request
        original_update_conversation = routes.crud.update_conversation
        original_send_meta = routes._send_whatsapp_message

        try:
            routes.crud.get_customer_by_phone = lambda db, phone: None
            routes.crud.create_customer = lambda db, payload: SimpleNamespace(id=42, phone="393331234567", address=None, city=None)
            routes.crud.get_conversation_by_customer_channel = lambda db, business_id, customer_id, channel: None
            routes.crud.create_conversation = lambda db, business_id, customer_id, service_request_id, channel: SimpleNamespace(
                id=7,
                service_request_id=None,
                status=None,
            )
            routes.crud.create_message = lambda db, **kwargs: SimpleNamespace(id=1)
            routes.crud.get_service_request = lambda db, service_request_id: None
            routes.crud.create_service_request = lambda db, payload: SimpleNamespace(id=99, description="ciao")
            routes.crud.update_conversation = lambda db, conv_id, **kwargs: SimpleNamespace(
                id=conv_id,
                service_request_id=kwargs.get("service_request_id"),
                status=kwargs.get("status"),
            )
            routes._send_whatsapp_message = lambda db, conversation_id, phone, body: calls.append((conversation_id, phone, body))

            response = routes._process_whatsapp_inbound(object(), "whatsapp:+393331234567", "ciao", 0, channel="meta")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], "whatsapp:+393331234567")
            self.assertIn("Perfetto, ho registrato il problema", calls[0][2])
        finally:
            routes.crud.get_customer_by_phone = original_get_customer_by_phone
            routes.crud.create_customer = original_create_customer
            routes.crud.get_conversation_by_customer_channel = original_get_conversation_by_customer_channel
            routes.crud.create_conversation = original_create_conversation
            routes.crud.create_message = original_create_message
            routes.crud.get_service_request = original_get_service_request
            routes.crud.create_service_request = original_create_service_request
            routes.crud.update_conversation = original_update_conversation
            routes._send_whatsapp_message = original_send_meta


if __name__ == "__main__":
    unittest.main()
