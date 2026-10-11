import importlib.util
import json
import pathlib
import subprocess
import unittest

spec = importlib.util.spec_from_file_location('patch_acp_fleet', pathlib.Path(__file__).with_name('patch-acp-fleet.py'))
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


class AcpFleetProtocolTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(['node', '-e', source], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_model_is_confirmed_before_effort_uses_updated_options(self):
        result = self.node('''
const calls=[]; const agent='opencode', sessionId='session-test', model='go-plan/model', thinking='max';
const spec={sessionConfig:true};
const sess={configOptions:[{id:'model',category:'model',type:'select',currentValue:'other/model',options:[{value:'go-plan/model'}]}]};
async function request(method, params) {
  calls.push({method,params});
  return {configOptions:[
    {id:'model',category:'model',type:'select',currentValue:'go-plan/model',options:[{value:'go-plan/model'}]},
    {id:'effort',category:'thought_level',type:'select',currentValue:params.configId==='effort'?'max':'low',options:[{value:'max'},{value:'low'}]}
  ]};
}
(async()=>{''' + patch.SESSION_OPTIONS + '''console.log(JSON.stringify(calls));})().catch(e=>{console.error(e);process.exitCode=1});
''')
        self.assertEqual([call['method'] for call in result], ['session/set_config_option'] * 2)
        self.assertEqual([call['params']['configId'] for call in result], ['model', 'effort'])
        self.assertEqual([call['params']['value'] for call in result], ['go-plan/model', 'max'])

    def test_unknown_model_is_rejected_without_a_prompt_or_config_mutation(self):
        result = self.node('''
const agent='opencode',sessionId='session-test',model='missing/model',thinking=null,spec={sessionConfig:true};let called=0;
const sess={configOptions:[{id:'model',category:'model',type:'select',currentValue:'other/model',options:[{value:'other/model'}]}]};
async function request(){called++;throw new Error('must not call');}
(async()=>{try{''' + patch.SESSION_OPTIONS + '''}catch(error){console.log(JSON.stringify({called,error:error.message}));}})();
''')
        self.assertEqual(result['called'], 0)
        self.assertIn('does not advertise', result['error'])

    def test_silent_model_rejection_is_not_reported_as_selected(self):
        result = self.node('''
const agent='opencode',sessionId='session-test',model='go-plan/model',thinking=null,spec={sessionConfig:true};
const sess={configOptions:[{id:'model',category:'model',type:'select',currentValue:'other/model',options:[{value:'go-plan/model'}]}]};
async function request(){return {configOptions:sess.configOptions};}
(async()=>{try{''' + patch.SESSION_OPTIONS + '''}catch(error){console.log(JSON.stringify({error:error.message}));}})();
''')
        self.assertIn('did not confirm', result['error'])

    def test_patch_is_idempotent_when_replacement_contains_original_anchor(self):
        anchor = '// session/load replays history; return only this follow-up'
        after = patch.SESSION_OPTIONS + anchor
        once = patch.replace_once(anchor, anchor, after)
        self.assertEqual(patch.replace_once(once, anchor, after), once)
        with self.assertRaises(ValueError):
            patch.replace_once(once + '\n' + anchor, anchor, after)

    def test_ambiguous_version_is_refused(self):
        with self.assertRaises(ValueError):
            patch.replace_once('old old', 'old', 'new')

    def test_namespaced_permission_request_keeps_the_existing_selection_policy(self):
        # Exercise the patched branch with standard, legacy, unrelated and empty requests.
        # The permission selection and cancellation bodies are intentionally untouched.
        source = '''
function answer(method, options) {
  if (method === 'request_permission') {
    const pick = options.find(o => /allow|proceed|yes|continue/i.test(`${o.kind || ''} ${o.optionId || ''} ${o.name || ''}`)) || options[0];
    return pick ? {outcome:{outcome:'selected',optionId:pick.optionId}} : {outcome:{outcome:'cancelled'}};
  }
  return {error:{code:-32601}};
}
'''
        transformed = patch.replace_once(source,
            "if (method === 'request_permission') {",
            "if (method === 'session/request_permission' || method === 'request_permission') {")
        rows = self.node(transformed + '''
const options=[{optionId:'deny_once',kind:'reject_once'},{optionId:'allow_once',kind:'allow_once'}];
console.log(JSON.stringify([
  answer('session/request_permission',options), answer('request_permission',options),
  answer('unrelated/request_permission',options), answer('session/request_permission',[])
]));
''')
        self.assertEqual(rows[0], {'outcome': {'outcome': 'selected', 'optionId': 'allow_once'}})
        self.assertEqual(rows[1], rows[0])
        self.assertEqual(rows[2], {'error': {'code': -32601}})
        self.assertEqual(rows[3], {'outcome': {'outcome': 'cancelled'}})

    def test_mcp_errors_are_marked_but_successful_turns_are_not(self):
        initial = 'function out(result) { const text=typeof result==="string"?result:JSON.stringify(result);\n  return { content: [{ type: "text", text }] };\n}'
        # Only the result formatter is exercised; resume-schema changes are separate.
        formatter = patch.patch_server(initial + '''
      sessionId: z.string().describe("Past session id"),
      prompt: z.string().describe("Follow-up prompt"),
    async ({ agent, sessionId, prompt, timeout }) =>
      bridge({ action: "resume", agent, sessionId, prompt, timeout }),
''').split('\n      sessionId:')[0]
        rows = self.node(formatter + '\nconsole.log(JSON.stringify([out(\'{"error":"rejected"}\'),out("[timeout] opencode"),out("[done/end_turn] opencode\\nOK")]));')
        self.assertTrue(rows[0]['isError'])
        self.assertTrue(rows[1]['isError'])
        self.assertNotIn('isError', rows[2])


if __name__ == '__main__':
    unittest.main()
