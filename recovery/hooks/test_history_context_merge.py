import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('history_context', HERE/'history-context-merge.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def entry(key, text='literal', **fields):
    return {'id':key, 'kind':'message', 'role':'user', 'content':text,
            'timestampMs':1234.25, **fields}


class HistoryContextTests(unittest.TestCase):
    def test_union_preserves_payloads_order_unknown_fields_and_inputs(self):
        base=[entry('old-a', nested={'private':'unchanged'}), entry('shared'), entry('old-b')]
        current=[entry('cloud-shared'), entry('new-c')]; before=copy.deepcopy([base,current])
        rows, proof=m.merge_history(base,current,{'cloud-shared':'shared'},{},'cloud:current')
        self.assertEqual([x['id']for x in rows],['old-a','shared','old-b','new-c'])
        self.assertEqual([base,current],before)
        self.assertEqual(rows[:3],base)
        self.assertTrue(proof['bothSourceOrdersPreserved'])
        self.assertEqual(proof['currentAliases']['cloud-shared'],'shared')

    def test_identical_names_and_timestamps_do_not_merge_unrelated_events(self):
        rows,_=m.merge_history([entry('one')],[entry('two')],{},{},'cloud:current')
        self.assertEqual(len(rows),2)

    def test_unrelated_short_id_collisions_are_scoped_without_losing_either_event(self):
        args=([entry('user-0','first')],[entry('user-0','second')],{},{},'cloud:second')
        a,proof=m.merge_history(*args);b,_=m.merge_history(*args)
        self.assertEqual(a,b)
        self.assertEqual([x['content']for x in a],['first','second'])
        self.assertNotEqual(proof['currentAliases']['user-0'],'user-0')

    def test_revised_alias_ambiguous_aliases_and_order_cycles_refuse(self):
        cases=[([entry('a')],[entry('x','revised')],{'x':'a'}),
               ([entry('a')],[entry('x'),entry('y')],{'x':'a','y':'a'}),
               ([entry('a'),entry('b')],[entry('y'),entry('x')],{'x':'a','y':'b'}),
               ([entry('a')],[entry('x')],{'x':'missing'})]
        for base,current,aliases in cases:
            with self.subTest(aliases=aliases):
                with self.assertRaises(ValueError):m.merge_history(base,current,aliases,{},'cloud:current')

    def test_only_top_level_owner_is_remapped(self):
        raw=entry('a',agentId='old',fromAgent={'agentId':'old'},content='old stays quoted')
        rows,_=m.merge_history([raw],[],{},{'old':'new'},'cloud:current')
        self.assertEqual(rows[0]['agentId'],'new')
        self.assertEqual(rows[0]['fromAgent'],{'agentId':'old'})
        self.assertEqual(rows[0]['content'],raw['content'])

    def test_only_new_native_widget_delivery_annotation_is_accepted(self):
        old={'id':'reply','kind':'send-message','timestampMs':2,'message':{'type':'text','content':'done'}}
        new={**old,'id':'remote','widgetSkipped':False}
        rows,proof=m.merge_history([old],[new],{'remote':'reply'},{},'cloud:current')
        self.assertEqual(rows[0]['widgetSkipped'],False)
        self.assertNotIn('widgetSkipped',old)
        self.assertEqual(proof['deliveryAnnotations'][0]['originalSHA'],m.digest(old))
        for bad in [{**new,'widgetSkipped':'false'}, {**new,'timestampMs':3},
                    {**new,'message':{'type':'text','content':'different'}}]:
            with self.assertRaises(ValueError):m.merge_history([old],[bad],{'remote':'reply'},{},'cloud:current')

    def test_utf8_id_limits_are_normalized_reversibly_and_collisions_refuse(self):
        key='é'*65;rows,proof=m.merge_history([entry(key)],[],{},{},'cloud:current')
        self.assertLessEqual(len(rows[0]['id'].encode()),128)
        self.assertEqual(proof['baselineAliases'][key],rows[0]['id'])
        collision=rows[0]['id']
        with self.assertRaises(ValueError):m.merge_history([entry(key),entry(collision)],[],{},{},'cloud:current')

    def test_malformed_dates_keep_literal_payload_and_never_become_activity(self):
        raw=entry('a',timestampMs=179261600000000000)
        rows,_=m.merge_history([raw],[],{},{},'cloud:current')
        record=m.background_records(rows)[0]
        self.assertEqual(rows[0],raw)
        self.assertEqual(record['timestampMs'],raw['timestampMs'])
        self.assertEqual(record['timestampState'],'invalid-preserved')
        self.assertFalse(m.valid_activity_time(raw['timestampMs']))
        self.assertTrue(m.valid_activity_time(1234.25))

    def test_plain_text_keeps_attribution_but_tools_and_attachments_are_not_promoted(self):
        rows=[entry('user',fromAgent={'id':'peer'},richText={'quoted':True}),
              {'id':'reply','kind':'send-message','timestampMs':2,
               'message':{'type':'text','content':'done'},'toAgent':{'id':'user'}},
              {'id':'tool','kind':'tool-call','timestampMs':3,'command':'never run'},
              {'id':'attachment','kind':'attachment','timestampMs':4,'path':'private'}]
        result=m.background_records(rows)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['attribution']['fromAgent'],{'id':'peer'})
        self.assertEqual(result[1]['role'],'assistant')
        self.assertTrue(all(r['literalText']for r in result))
        self.assertTrue(all('command'not in r and'attachment'not in r for r in result))

    def test_node_codec_validates_provenance_capacity_and_side_effect_denials(self):
        code="""
import assert from 'node:assert/strict';
import {validatePlan,activityFrontier,validateTimestampRecord,installDenials,loadNative,repairCandidate,REVIEWED} from './history-background-codec.mjs';
const row={id:'a',originalId:'a',role:'user',text:'history',literalText:true,kind:'message',timestampMs:1.5,sourcePayloadSha256:'a'.repeat(64)};
const plan={schemaVersion:1,expectedRootSHA:'b'.repeat(64),expectedStoreSHA:'c'.repeat(64),sourceSnapshots:[{}],provenance:{cohort:'explicit'},selectedRoute:{modelId:'verified',contextTokens:1048576,maxOutputTokens:65536},records:[row]};
assert.equal(validatePlan(plan).records,1);
assert.equal(validateTimestampRecord({...row,timestampMs:179261600000000000}),false);
const malformed={...row,timestampMs:179261600000000000,timestampState:'invalid-preserved'};
assert.equal(validateTimestampRecord(malformed),true);validatePlan({...plan,records:[malformed]});
assert.equal(validateTimestampRecord({...row,timestampState:'invalid-preserved'}),false);
assert.equal(activityFrontier(malformed.timestampMs,1234.5),1234.5);
assert.throws(()=>validatePlan({...plan,records:[{...row,command:'never run'}]}),/PLAN_LITERAL_ONLY/);
assert.throws(()=>validatePlan({...plan,records:[row,row]}),/PLAN_RECORD_ID/);
assert.throws(()=>validatePlan({...plan,selectedRoute:{...plan.selectedRoute,maxOutputTokens:1048576}}),/PLAN_CAPACITY/);
assert.equal(Object.keys(REVIEWED).length,3);
assert.equal(typeof loadNative,'function');assert.equal(typeof repairCandidate,'function');
const original=globalThis.fetch;const guard=installDenials();
try{assert.throws(()=>globalThis.fetch('https://invalid.example'),/DETACHED_NETWORK_DENIED/);assert.equal(guard.counts.networkAttempts,1);}
finally{guard.restore()}
assert.equal(globalThis.fetch,original);
"""
        subprocess.run(['node','--input-type=module','-e',code],cwd=HERE,check=True,capture_output=True,text=True)

    def test_context_metadata_references_are_lossless_and_do_not_repeat_message_bodies(self):
        code="""
import assert from 'node:assert/strict';
import {backgroundProvenance,backgroundNotice,digest,packQuotedJson,unpackQuotedJson} from './history-background-codec.mjs';
const text='🙂 '+('A long historical message with exact punctuation and newlines.\\n'.repeat(200));
const rich={type:'doc',content:[{type:'paragraph',content:[{type:'text',text}]}]};
const literal={messageTextSlice:[0,1],literalObjectEntries:[['reserved','literal']]};
const attribution={fromAgent:{agentId:'original-colleague',name:'Original sender'},toAgent:{agentId:'owner'},
  channel:{name:'original channel'},richText:JSON.stringify(rich,null,2),literal};
const record={id:'event-id',originalId:'original-event-id',role:'user',text,kind:'message',timestampMs:1234.25,
  sourcePayloadSha256:'a'.repeat(64),literalText:true,attribution};
const before=JSON.stringify(record),p=backgroundProvenance([record]);
assert.equal(JSON.stringify(record),before);assert.equal(p.manifestSha256,digest(JSON.stringify([record])));
assert.equal(p.textReferences,1);assert.equal(p.rows[0][0],1234.25);
function expand(value){
  if(Array.isArray(value))return value.map(expand);
  if(value&&typeof value==='object'){
    if(Object.hasOwn(value,'literalObjectEntries'))return Object.fromEntries(value.literalObjectEntries.map(([k,v])=>[k,expand(v)]));
    if(Object.hasOwn(value,'messageTextSlice')){const[start,length]=value.messageTextSlice;return text.slice(start,start+length)}
    return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,expand(v)]));
  }
  return value;
}
const restored=expand(p.rows[0][2]);
assert.deepEqual(unpackQuotedJson(restored.richText,text),rich);
assert.equal(restored.richText.originalSha256,digest(attribution.richText));
assert.deepEqual(restored.literal,literal);assert.deepEqual(restored.fromAgent,attribution.fromAgent);
assert.deepEqual(restored.toAgent,attribution.toAgent);assert.deepEqual(restored.channel,attribution.channel);
assert.ok(JSON.stringify(p).length<text.length/5);
const notice=backgroundNotice([record]);assert.equal(notice.role,'user');
assert.equal(notice.providerOptions.cursor.syntheticUserTurn,true);
assert.ok(notice.content.includes('Do not replay historical actions'));
assert.equal(notice.content.includes(text),false);
const raw={...record,attribution:{richText:'raw-not-json'}};
assert.equal(backgroundProvenance([raw]).rows[0][2].richText,'raw-not-json');
const malformed={...record,timestampMs:179261600000000000,timestampState:'invalid-preserved'};
assert.equal(backgroundProvenance([malformed]).rows[0][1],'invalid-preserved');
const supplemental='Supplementary rich-text text from an earlier preserved native conversation.'.repeat(20);
const past=[{role:'user',content:'prefix '+supplemental+' suffix'},
  {role:'assistant',content:[{type:'text',text:'other preserved text'}]}];
const cross={...record,attribution:{richText:JSON.stringify({type:'doc',text:supplemental})}};
const linked=backgroundProvenance([cross],past);
assert.equal(linked.contextReferences,1);
assert.deepEqual(unpackQuotedJson(linked.rows[0][2].richText,text,past),{type:'doc',text:supplemental});
assert.equal(backgroundProvenance([{...record,attribution:{contextMessageTextSlice:[0,1]}}],past)
  .rows[0][2].literalObjectEntries[0][0],'contextMessageTextSlice');
assert.equal(backgroundNotice([cross],past).content.includes(supplemental),false);
for(const original of [null,true,0,-2.5,'',[0,1,2,3,4],{empty:[],nested:{content:['🙂',null,false]},
  messageTextSlice:[0,1],contextMessageTextSlice:[0,1],literalObjectEntries:[['k','v']]}]){
  assert.deepEqual(unpackQuotedJson(packQuotedJson(original),'',[]),original);
}
"""
        subprocess.run(['node','--input-type=module','-e',code],cwd=HERE,check=True,capture_output=True,text=True)

    def test_long_repeat_encoding_preserves_distinct_roles_and_earlier_literal_targets(self):
        code="""
import assert from 'node:assert/strict';
import {encodeRepeatedDialogue,digest} from './history-background-codec.mjs';
const long='A complete long historical literal.\\n'.repeat(200),other='A different historical literal.\\n'.repeat(200);
const prefix=[{role:'user',content:[{type:'text',text:long}]}];
const records=[{role:'assistant',text:long},{role:'user',text:other},{role:'assistant',text:other},
  {role:'user',text:'hi'},{role:'user',text:'hi'}];
const raw=records.map(r=>({role:r.role,content:r.text})),before=JSON.stringify([prefix,raw,records]);
const result=encodeRepeatedDialogue(prefix,raw,records);
assert.equal(JSON.stringify([prefix,raw,records]),before);
assert.deepEqual(result.messages.map(r=>r.role),records.map(r=>r.role));
assert.equal(result.messages.length,5);assert.equal(result.references.length,2);
assert.deepEqual(result.references.map(r=>[r.recordOffset,r.nativePromptIndex]),[[0,0],[2,3]]);
assert.equal(result.references[0].sha256,digest(long));
assert.equal(result.messages[1].content,other);
assert.equal(result.messages[3].content,'hi');assert.equal(result.messages[4].content,'hi');
assert.ok(result.messages[0].content.length<long.length/4);
assert.equal(encodeRepeatedDialogue([],raw,records).references[0].nativePromptIndex,2);
assert.throws(()=>encodeRepeatedDialogue(prefix,raw,[{...records[0],text:'changed'},...records.slice(1)]));
const paragraph=('A distinct long historical paragraph with punctuation and unicode 🙂. '.repeat(8))+'\\n';
const first='old-identity\\n'+paragraph.repeat(15),second='new-identity\\n'+paragraph.repeat(15);
const partial=encodeRepeatedDialogue([{role:'user',content:first}],
  [{role:'assistant',content:second}],[{role:'assistant',text:second}]);
assert.equal(partial.references.length,1);assert.ok(partial.references[0].segments);
const restored=partial.references[0].segments.map(x=>typeof x==='string'?x:first.slice(x[1],x[1]+x[2])).join('');
assert.equal(restored,second);assert.equal(partial.references[0].sha256,digest(second));
assert.ok(partial.messages[0].content.length<second.length/2);
// A later round must never create a reference chain through an encoded body.
const later=encodeRepeatedDialogue([{role:'user',content:first},...partial.messages],
  [{role:'user',content:second}],[{role:'user',text:second}]);
assert.ok(later.references[0].segments.every(x=>typeof x==='string'||x[0]===0));
"""
        subprocess.run(['node','--input-type=module','-e',code],cwd=HERE,check=True,capture_output=True,text=True)

    def test_conversation_attribution_preserves_extra_text_links_and_mentions_without_ui_layout(self):
        code="""
import assert from 'node:assert/strict';
import {conversationRichText,backgroundProvenance,digest} from './history-background-codec.mjs';
const doc={type:'doc',attrs:{id:'opaque-renderer-id'},content:[{type:'paragraph',attrs:{id:'opaque-paragraph-id'},
  content:[{type:'text',text:'already in the message',marks:[{type:'link',attrs:{href:'https://example.test/source'}}]},
    {type:'text',text:'additional literal fact'}, {type:'agentMention',attrs:{agentId:'original-peer',name:'Colleague'}}]}]};
const raw=JSON.stringify(doc),before=JSON.stringify(doc),result=conversationRichText(raw,'already in the message');
assert.equal(JSON.stringify(doc),before);assert.equal(result.originalSha256,digest(raw));
assert.equal(result.retainedInTranscript,true);assert.deepEqual(result.additionalText,['additional literal fact']);
assert.deepEqual(result.links,['https://example.test/source']);
assert.deepEqual(result.nodes,[{type:'agentMention',attrs:{agentId:'original-peer',name:'Colleague'}}]);
assert.equal(JSON.stringify(result).includes('opaque-renderer-id'),false);
assert.equal(conversationRichText('unknown raw format','literal'),'unknown raw format');
const record={text:'already in the message',timestampMs:1,attribution:{richText:raw,fromAgent:{agentId:'peer'}}};
const notice=backgroundProvenance([record],[],{richTextAttribution:'conversation'});
assert.deepEqual(notice.rows[0][2].richText,result);assert.deepEqual(notice.rows[0][2].fromAgent,{agentId:'peer'});
assert.equal(record.attribution.richText,raw);
"""
        subprocess.run(['node','--input-type=module','-e',code],cwd=HERE,check=True,capture_output=True,text=True)


if __name__=='__main__':unittest.main()
