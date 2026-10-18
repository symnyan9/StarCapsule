"""Bounded authored-copy translation, independent of mesh size or wall-clock timing."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ASSET = Path(__file__).resolve().parents[1] / "src" / "cfd_review" / "assets" / "field-viewer.js"
NODE = shutil.which("node")


def run_node(check):
    if not NODE:
        raise unittest.SkipTest("Node unavailable; browser language checks run separately")
    source = ASSET.read_text(encoding="utf-8")
    phrases = json.loads(re.search(r"const phrases=(\{[^\n]+\}),keys=", source)[1])
    script = """
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const context={window:{},document:{documentElement:{lang:'en'}}};vm.createContext(context);
const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInContext(source.slice(0,source.indexOf('(() => {')),context);
context.input=input;
""" + check
    result = subprocess.run([NODE, "-e", script, str(ASSET)], input=json.dumps(phrases),
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class BrowserTranslationChecks(unittest.TestCase):
    def test_authored_phrases_punctuation_languages_and_source_names(self):
        result = run_node(r"""
vm.runInContext(`
 const t=StarCapsuleI18n.t,raw=StarCapsuleI18n.raw;
 const check=(condition,label)=>{if(!condition)throw Error(label)};
 for(const [zh,en] of Object.entries(input))check(t(zh)===en,'English phrase: '+zh);
 for(const value of ['', 'ABC / CpT = 1.05', '<span>Surface Cp</span>', '−Y / +Y · 0.98'])check(t(value)===value,'ASCII/symbol preservation');
 check(t('。')==='.'&&t('，：；')===', : ; ','English punctuation');
 check(t\`表面 \${raw('复位 / Surface Cp')}\`==='Surface 复位 / Surface Cp','literal English source');
 StarCapsuleI18n.set('zh-CN',null);
 for(const zh of Object.keys(input))check(t(zh)===zh,'Chinese phrase: '+zh);
 check(t('。')==='。'&&t('，：；')==='，：；','Chinese punctuation');
 check(t\`表面 \${raw('复位 / Surface Cp')}\`==='表面 复位 / Surface Cp','literal Chinese source');
 StarCapsuleI18n.set('en',null);check(t('复位')==='Reset','source label does not replace authored UI copy');
`,context);
process.stdout.write(JSON.stringify({passed:true,phrases:Object.keys(input).length}));
""")
        self.assertTrue(result["passed"])
        self.assertGreater(result["phrases"], 400)

    def test_repeated_mesh_messages_do_not_scan_dictionary_for_empty_chunks(self):
        result = run_node(r"""
vm.runInContext(`
 const original=String.prototype.split;let splits=0;
 String.prototype.split=function(...args){splits++;return original.apply(this,args)};
 try{for(let i=0;i<1000;i++){
  const message=StarCapsuleI18n.t\`\${'mesh-source'}：三角面重复顶点索引\`;
  if(message!=='mesh-source: repeated vertex index in triangle')throw Error('Wrong translated mesh message');
 }}finally{String.prototype.split=original;}
 if(splits!==0)throw Error('Mesh messages performed '+splits+' dictionary split operations');
`,context);
process.stdout.write(JSON.stringify({passed:true,iterations:1000,dictionarySplits:0}));
""")
        self.assertTrue(result["passed"])
        self.assertEqual(result["dictionarySplits"], 0)


if __name__ == "__main__":
    unittest.main()
