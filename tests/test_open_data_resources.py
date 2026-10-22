"""開放資料匯入、鄉鎮與既有求助入口的回歸檢查；不連外。"""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import NANTOU_RESOURCES, TOWNSHIPS, app, referral_resources
from models import database


class OpenDataResourcesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.resources = {r['id']: r for r in NANTOU_RESOURCES}

    def test_import_keeps_all_24_records_without_duplicate_ids(self):
        imported = [r for r in NANTOU_RESOURCES if r.get('source_dataset_id') == '168126']
        self.assertEqual(len(imported), 24)
        self.assertEqual(len(self.resources), len(NANTOU_RESOURCES))
        self.assertEqual({r['township'] for r in imported if r['id'].startswith('ph_')}, TOWNSHIPS)
        self.assertIn('hosp_puli_vgh', self.resources)
        self.assertIn('therapy_weisheng', self.resources)

    def test_phone_corrections_keep_original_source_values(self):
        cases = [('cmhc_nantou', '049-2202662', '(049)2202636'),
                 ('hosp_nantou', '049-2231150', '(049)22231150')]
        for key, corrected, original in cases:
            with self.subTest(resource=key):
                item = self.resources[key]
                self.assertEqual(item['phone'], corrected)
                self.assertEqual(item['source_record']['連絡電話'].strip(), original)
                self.assertTrue(item['phone_source_url'].startswith('https://'))

    def test_csv_does_not_imply_free_online_or_youth_eligibility(self):
        for item in NANTOU_RESOURCES:
            if item.get('source_dataset_id') == '168126':
                with self.subTest(resource=item['id']):
                    self.assertIsNone(item['is_free'])
                    self.assertIsNone(item['has_online_counseling'])
                    self.assertIsNone(item['target'])
                    self.assertIsNone(item['service_hours'])

    def test_every_township_gets_its_station_and_existing_help_contacts(self):
        for township in TOWNSHIPS:
            with self.subTest(township=township):
                result = self.client.get('/api/resources', query_string={'township': township})
                self.assertEqual(result.status_code, 200)
                resources = result.json['resources']
                stations = [r for r in resources if r['id'].startswith('ph_')]
                self.assertEqual(len(stations), 1)
                self.assertEqual(stations[0]['township'], township)
                centers = [r for r in resources if r['id'].startswith('cmhc_')]
                self.assertEqual(len(centers), 1)
                self.assertEqual(len(referral_resources(township)), 3)
                ids = {r['id'] for r in resources}
                self.assertTrue({'stu_center', 'crisis_1925', 'crisis_1995',
                                 'crisis_1980', 'crisis_110_119'} <= ids)

    def test_imported_names_are_searchable_in_their_categories(self):
        checks = [('埔里鎮', '醫院', '榮民', 'hosp_puli_vgh'),
                  ('南投市', '診所', '致遠', 'clinic_zhiyuan'),
                  ('草屯鎮', '治療所', '唯聆', 'therapy_weiling')]
        for township, category, keyword, expected in checks:
            with self.subTest(resource=expected):
                result = self.client.get('/api/resources', query_string={
                    'township': township, 'category': category, 'keyword': keyword})
                self.assertEqual([r['id'] for r in result.json['resources']], [expected])

    def test_all_resources_and_national_only_filters(self):
        self.assertEqual(self.client.get('/api/resources').json['total'], 31)
        result = self.client.get('/api/resources?township=全國通用').json
        self.assertEqual({r['id'] for r in result['resources']},
                         {'crisis_1925', 'crisis_1995', 'crisis_1980', 'crisis_110_119'})


    def test_resource_page_reuses_township_without_creating_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(database, 'DB_PATH', str(Path(temporary) / 'test.db')):
                database.init_db()
                self.client.get('/')
                with self.client.session_transaction() as session:
                    csrf = session['csrf_token']
                onboard = self.client.post('/api/onboarding', headers={'X-CSRF-Token': csrf}, json={
                    'student_email': 'resources@example.edu.tw', 'student_alias': '小安',
                    'student_school': '測試高中', 'township': '仁愛鄉', 'privacy_acknowledged': True})
                self.assertEqual(onboard.status_code, 200)
                response = self.client.get('/resources')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'const initialTownship = "\\u4ec1\\u611b\\u9109";', response.data)
                self.assertEqual(database.get_all_cases(), [])


if __name__ == '__main__':
    unittest.main()
