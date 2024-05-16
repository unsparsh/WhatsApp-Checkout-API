# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.


import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from elements import Amount, Header, Item

URL = "https://graph.facebook.com/v19.0"


class CheckoutBase(ABC):
    """
    WhatsApp Checkout API Base class
    """

    _phone_number_to_id_map = {}

    @abstractmethod
    def get_access_token(self) -> str:
        """
        Get the access token for the WABA
        """
        pass

    @abstractmethod
    def get_waba(self) -> str:
        """
        Get WhatsApp Business Account ID, implement your own logic to get it
        """
        pass

    @abstractmethod
    def get_payment_configuration(self) -> str:
        """
        Get the payment configuration id for the WABA
        """
        pass

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": "Bearer " + self.get_access_token(),
            "Content-Type": "application/json",
        }

    def _load_phone_numbers(self) -> None:
        headers = self._get_headers()
        waba = self.get_waba()
        r = requests.get(f"{URL}/{waba}/phone_numbers", headers=headers)
        if r.status_code != 200:
            raise Exception(f"Error on getting phone number id map {r.content}")

        data = json.loads(r.text)["data"]
        if len(data) == 0:
            raise Exception("There are no phone numbers in the WABA")

        for d in data:
            # translate number like "+1 631-555-5555" to "16315555555"
            phone_number = "".join(
                c for c in d["display_phone_number"] if c in "0123456789"
            )
            self._phone_number_to_id_map[phone_number] = d["id"]

    def _get_sender_phone_number_id(self, phone_number: str) -> str:
        if not self._phone_number_to_id_map:
            self._load_phone_numbers()
        return self._phone_number_to_id_map[phone_number]

    def send_order_details_msg(
        self,
        goods_type: str,
        sender_phone_number: str,
        recipient_phone_number: str,
        reference_id: str,
        msg_body: str,
        items: List[Item],
        tax_amount: Amount,
        tax_desc: Optional[str] = None,
        shipping_amount: Optional[Amount] = None,
        shipping_desc: Optional[str] = None,
        discount_amount: Optional[Amount] = None,
        discount_desc: Optional[str] = None,
        discount_program_name: Optional[str] = None,
        catalog_id: Optional[str] = None,
        msg_header: Optional[Header] = None,
        msg_footer: Optional[str] = None,
        expiration_in_sec: Optional[str] = None,
        expiration_desc: Optional[str] = None,
        # ) -> requests.Response:
    ) -> None:
        """
        Send the order details to customer via WhatsApp Business API
        """
        http_headers = self._get_headers()
        phone_number_id = self._get_sender_phone_number_id(sender_phone_number)
        interactive: Dict[str, Any] = {
            "type": "order_details",
            "body": {
                "text": msg_body,
            },
            "action": {
                "name": "review_and_pay",
                "parameters": {
                    "reference_id": reference_id,
                    "type": goods_type,
                    "payment_type": "upi",
                    "payment_configuration": self.get_payment_configuration(),
                    "currency": "INR",
                    "order": {
                        "status": "pending",
                    },
                },
            },
        }
        if msg_header:
            hd: Dict[str, Any] = {"type": msg_header.type}
            if hd["type"] == "text" and msg_header.text:
                hd["text"] = msg_header.text
            elif hd["type"] == "image" and msg_header.image_link:
                hd["image"] = {
                    "link": msg_header.image_link,
                }
            else:
                raise ValueError(f"Invalid header type {msg_header.type}")
            interactive["header"] = hd
        if msg_footer:
            interactive["footer"] = {"text": msg_footer}
        if catalog_id:
            interactive["action"]["parameters"]["order"]["catalog_id"] = catalog_id
        if expiration_in_sec:
            interactive["action"]["parameters"]["order"]["expiration"] = {
                "timestamp": expiration_in_sec
            }
            if expiration_desc:
                interactive["action"]["parameters"]["order"]["expiration"][
                    "description"
                ] = expiration_desc
        total = 0
        offset = items[0].amount.offset
        item_list = []
        for item in items:
            it: Dict[str, Any] = {
                "name": item.name,
                "amount": item.amount.toJSON(),
                "quantity": item.quantity,
            }
            if item.retailer_id:
                it["retailer_id"] = item.retailer_id
            if item.image_link:
                it["image"] = {
                    "link": item.image_link,
                }
            if item.sale_amount:
                it["sale_amount"] = item.sale_amount.toJSON()
                am = item.sale_amount
            else:
                am = item.amount
            if offset != am.offset:
                raise ValueError("Item amount must have the same offset as others")
            total += am.value * item.quantity
            if item.country_of_origin:
                it["country_of_origin"] = item.country_of_origin
            if item.importer_name:
                it["importer_name"] = item.importer_name
            if item.importer_address:
                it["importer_address"] = item.importer_address.__dict__
            item_list.append(it)
        interactive["action"]["parameters"]["order"]["items"] = item_list
        interactive["action"]["parameters"]["order"]["subtotal"] = {
            "value": total,
            "offset": offset,
        }
        if tax_amount:
            total += tax_amount.value
            tax: Dict[str, Any] = {
                "value": tax_amount.value,
                "offset": offset,
            }
            if tax_desc:
                tax["description"] = tax_desc
            interactive["action"]["parameters"]["order"]["tax"] = json.dumps(tax)
        if shipping_amount:
            total += shipping_amount.value
            shipping: Dict[str, Any] = {
                "value": shipping_amount.value,
                "offset": offset,
            }
            if shipping_desc:
                shipping["description"] = shipping_desc
            interactive["action"]["parameters"]["order"]["shipping"] = json.dumps(
                shipping
            )
        if discount_amount:
            total -= discount_amount.value
            discount: Dict[str, Any] = {
                "value": discount_amount.value,
                "offset": offset,
            }
            if discount_desc:
                discount["description"] = discount_desc
            if discount_program_name:
                discount["discount_program_name"] = discount_program_name
            interactive["action"]["parameters"]["order"]["discount"] = json.dumps(
                discount
            )
        interactive["action"]["parameters"]["total_amount"] = Amount(
            total, offset
        ).toJSON()
        request = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone_number,
            "type": "interactive",
            "interactive": interactive,
        }
        print("order details request is:\n{}".format(json.dumps(request, indent=4)))
        # in the request, the interactive field needs to be a json string
        # so we need to convert the dict into a string after the printing
        request["interactive"] = json.dumps(interactive)
        response = requests.post(
            url=f"{URL}/{phone_number_id}/messages", data=request, headers=http_headers
        )
        print("\norder details response is:\n{}".format(response.json()))

    def send_order_status_msg(
        self,
        sender_phone_number: str,
        recipient_phone_number: str,
        reference_id: str,
        msg_body: str,
        status: str,
        desc: Optional[str] = None,
    ) -> None:
        """
        Send the status of an order to customer via WhatsApp Business API.
        Returns True if successful else False
        """
        http_headers = self._get_headers()
        phone_number_id = self._get_sender_phone_number_id(sender_phone_number)
        interactive: Dict[str, Any] = {
            "type": "order_status",
            "body": {"text": msg_body},
            "action": {
                "name": "review_order",
                "parameters": {
                    "reference_id": reference_id,
                    "order": {
                        "status": status,
                    },
                },
            },
        }
        if desc:
            interactive["action"]["parameters"]["order"]["description"] = desc
        request = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone_number,
            "type": "interactive",
            "interactive": interactive,
        }
        print("\n\norder status request is:\n{}".format(json.dumps(request, indent=4)))
        # in the request, the interactive field needs to be a json string
        # so we need to convert the dict into a string after the printing
        request["interactive"] = json.dumps(interactive)
        response = requests.post(
            url=f"{URL}/{phone_number_id}/messages", data=request, headers=http_headers
        )
        print("\norder status response is:\n{}".format(response.json()))