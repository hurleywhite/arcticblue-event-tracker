import unittest
from unittest.mock import patch
from api import opportunities as api

class BookingAPI(unittest.TestCase):
    def test_editor_required(self):
        self.assertEqual(api._post(None, '', {'action':'save_target_account','name':'Test'})[0],403)
    def test_dates(self):
        for value in ['2026-02-30','2026-13-01','invalid']:
            with self.assertRaises(ValueError): api._clean_date(value)
        self.assertEqual(api._clean_date('2028-02-29'),'2028-02-29')
    def test_trip_validation(self):
        with self.assertRaises(ValueError): api._post(None,'editor',{'action':'add_travel_window','person_key':'thor','city':'Munich','source':'confirmed','start_date':'2026-10-02','end_date':'2026-10-01'})
    def test_target_write(self):
        with patch.object(api,'_insert',return_value=[{'id':1}]) as insert:
            result=api._post(None,'editor',{'action':'save_target_account','name':' Buyer ','city':'London','admin':True})
            self.assertEqual(result[0],200)
            self.assertEqual(insert.call_args.args[1]['name'],'Buyer')
            self.assertNotIn('admin',insert.call_args.args[1])
    def test_private_data_is_not_returned_publicly(self):
        with patch.object(api,'_select',return_value=[]) as select:
            result=api._get_payload('')
            self.assertEqual(result['target_accounts'],[])
            self.assertEqual(result['travel_windows'],[])
            self.assertFalse(any(call.args[0] in ['travel_windows','target_accounts'] for call in select.call_args_list))

if __name__=='__main__':unittest.main()
