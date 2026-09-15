import unittest
from unittest.mock import patch
from api import workflow, calendars, events


class WorkflowTests(unittest.TestCase):
    def test_all_actions_require_editor(self):
        for action in ('connect_attio','connect_calendar','search_contacts','save_workspace','save_trip','preview_calendar'):
            self.assertEqual(workflow._post('',{'action':action})[0],403)

    def test_calendar_url_cannot_target_other_hosts_or_redirect_endpoints(self):
        for url in ('http://127.0.0.1/calendar.ics','https://calendar.google.com.evil.test/calendar.ics',
                    'https://calendar.google.com/calendar/ical/a/private-abc/basic.ics?redirect=elsewhere',
                    'https://calendar.google.com/redirect?url=https://evil.test'):
            with self.assertRaises(ValueError): calendars._fetch_google_feed(url)

    def test_calendar_dates_cancelled_and_virtual(self):
        raw=calendars._parse_ics('BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:one\nDTSTART;VALUE=DATE:20260917\nDTEND;VALUE=DATE:20260921\nSUMMARY:Munich\nTRANSP:TRANSPARENT\nEND:VEVENT\nBEGIN:VEVENT\nUID:two\nDTSTART;VALUE=DATE:20260918\nSUMMARY:London\nSTATUS:CANCELLED\nEND:VEVENT\nBEGIN:VEVENT\nUID:three\nDTSTART;VALUE=DATE:20260919\nSUMMARY:New York\nLOCATION:Zoom\nEND:VEVENT\nEND:VCALENDAR')
        blocks,_=calendars._normalize(raw,'2026-09-15','2027-01-01')
        candidates=calendars._trip_candidates('thor',blocks)
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['end_date'],'2026-09-20')
        self.assertEqual(candidates[0]['source_event_id'],'one')
        self.assertEqual(candidates[0]['confidence'],'Needs review')

    def test_personal_calendar_not_fetched_for_anonymous_viewer(self):
        with patch.object(calendars,'_feeds',return_value=[{'name':'Thor','url':'secret','kind':'person'}]),patch.object(calendars,'_http') as fetch:
            result=calendars._gather(False)
            fetch.assert_not_called()
            self.assertEqual(result['busy'],{})
            self.assertEqual(result['trip_candidates'],[])

    def test_draft_does_not_count_as_sent(self):
        d=workflow._clean_document({'document':{'route':'Speaker pitch','status':'Ready','body':'Reviewed draft','admin':'bad'}})
        self.assertEqual(d['sent_at'],'')
        self.assertNotIn('admin',d)
        with self.assertRaises(ValueError): workflow._clean_document({'document':{'route':'Speaker pitch','status':'Sent'}})

    def test_optimistic_concurrency_does_not_overwrite(self):
        with patch.object(workflow.db,'_http_json',return_value=(200,[])):
            status,_=workflow._post('hurley@arcticblue.ai',{'action':'save_workspace','source_table':'manual_events','source_key':'1','version':3,'document':{'route':'Speaker pitch','status':'Drafting'}})
            self.assertEqual(status,409)

    def test_existing_calendar_trip_updates_instead_of_duplicates(self):
        with patch.object(workflow.db,'_select',return_value=[{'id':3}]),patch.object(workflow.db,'_patch',return_value=[{'id':3}]) as update,patch.object(workflow.db,'_insert') as insert:
            status,_=workflow._post('hurley@arcticblue.ai',{'action':'save_trip','person_key':'thor','city':'Munich','start_date':'2026-09-17','end_date':'2026-09-20','source_event_id':'one'})
            self.assertEqual(status,200);update.assert_called_once();insert.assert_not_called()

    def test_baft_rejected_even_without_model_key(self):
        with patch.object(events,'OPENAI_API_KEY',''):
            self.assertEqual(events._evaluate_event({'name':'2027 International Trade and Payments Conference','url':None},set())['decision'],'reject')

if __name__=='__main__': unittest.main()
