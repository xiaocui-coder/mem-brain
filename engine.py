# -*- coding: utf-8 -*-
"""
Memory Skill — Core Engine
===========================
记忆 + 推理 + 关联 + 感知增强 四位一体
无鉴权版本，基于左脑 v3.16 功能重新实现

核心类：
  MemoryEngine     — 知识图谱记忆引擎
  GenreClassifier  — 体裁分类器（8种体裁）
  KnowledgeInferrer— 知识推论引擎
  DeepReason       — 深度推理引擎
  ContextMemoryLayer — 三层上下文记忆
  DataAnalyzer     — 数据分析引擎
  Summarizer       — 文章总结引擎
"""

import json, os, sys, re, time, math, random, hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from collections import Counter

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ===== 路径常量 =====
SKILL_DIR = Path(__file__).resolve().parent
DATA_DIR = SKILL_DIR / "data"
DATA_FILE = DATA_DIR / "memory_duck_data.json"
ENTANGLE_FILE = DATA_DIR / "entanglement_data.json"
INJECT_FILE = SKILL_DIR / "_inject.md"
DB_PATH = DATA_DIR / "left_brain.db"
IDENTITY_TEMPLATE = SKILL_DIR / "IDENTITY.md"
VERSION_FILE = SKILL_DIR / "version.txt"
MEMORY_UUID = DATA_DIR / "uuid"
SETUP_FLAG = DATA_DIR / ".setup_done"

DATA_DIR.mkdir(exist_ok=True)
DATA_FILE.parent.mkdir(exist_ok=True)

# ===== 版本 =====
VERSION = "1.0"

# ===== Session ID 生成 =====
def _new_session_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + f"{random.randint(1000,9999)}"


# ============================================================
# 工具函数
# ============================================================

def _hash_64(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _simhash(text: str, hash_bits: int = 64) -> int:
    """SimHash 实现 — 语义相似度匹配"""
    tokens = list(text)
    if not tokens:
        return 0
    v = [0] * hash_bits
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16)
        for i in range(hash_bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    result = 0
    for i in range(hash_bits):
        if v[i] > 0:
            result |= (1 << i)
    return result


def _simhash_distance(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


def _extract_keywords(text: str) -> List[str]:
    """从文本中提取关键词（中文bigram + 英文单词）"""
    if not text:
        return []
    stopwords = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一',
                 '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着',
                 '没有', '看', '好', '自己', '这', '他', '她', '它', '们', '那',
                 '什么', '怎么', '如何', '哪', '为什么', '吗', '吧', '呢', '啊',
                 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                 'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
                 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through'}

    tokens = []
    # 中文：用 bigram（连续2字组合）
    cjk_chars = re.findall(r'[一-鿿]+', text)
    for segment in cjk_chars:
        if len(segment) >= 2:
            for i in range(len(segment) - 1):
                bigram = segment[i:i+2]
                if bigram not in stopwords:
                    tokens.append(bigram)
        elif segment not in stopwords:
            tokens.append(segment)

    # 英文/数字：按空格分割
    en_tokens = re.findall(r'[a-zA-Z][a-zA-Z0-9_]+', text)
    for t in en_tokens:
        if t.lower() not in stopwords:
            tokens.append(t)

    return tokens


# ============================================================
# GenreClassifier — 体裁分类器（8种体裁）
# ============================================================

class GenreClassifier:
    """体裁分类器 — 8种体裁检测 + 骨架提取 + 统一管线"""

    GENRES = ['process', 'paper', 'definition', 'argument',
              'data_summary', 'dialogue', 'essay', 'knowledge']

    # 体裁关键词权重
    GENRE_KEYWORDS = {
        'process': ['第一步', '第二步', '首先', '然后', '接着', '最后', '之后', '步骤',
                    '流程', '操作', '执行', '安装', '配置', '运行', '开始', '完成'],
        'paper': ['摘要', '引言', '方法', '结论', '研究', '实验', '结果表明', '本文提出',
                  '分析表明', '文献', '综述', '关键词', '参考文献'],
        'definition': ['是指', '定义', '概念', '含义', '即', '也就是说', '所谓',
                       '是一种', '分为', '包括', '由...组成'],
        'argument': ['因为', '所以', '因此', '然而', '但是', '虽然', '尽管', '如果',
                     '那么', '否则', '由于', '导致', '从而', '综上'],
        'data_summary': ['增长', '下降', '同比增长', '营收', '利润', '收入', '达到',
                         '%', '亿元', '万元', '万', '亿', '亿美元'],
        'dialogue': ['哈哈', '好的', '嗯嗯', '对吧', '呢', '啊', '呀', '哦',
                     '嘻嘻', '嘿嘿', '谢谢', '麻烦', '请问'],
        'essay': ['记得', '当时', '后来', '小时候', '以前', '曾经', '那时候',
                  '第一次', '回忆', '感受', '觉得'],
    }

    ACTION_PATTERNS = {
        'learn': [r'帮我记住', r'记住', r'记录', r'学习', r'保存', r'添加知识'],
        'query': [r'.*是什么', r'.*是什么的', r'什么是', r'谁知道', r'查一下',
                  r'查找', r'搜索', r'找', r'.*什么时候', r'.*在哪里', r'.*在哪',
                  r'.*在哪里', r'.*多少', r'.*是谁', r'.*定在', r'.*在哪儿'],
        'analyze': [r'分析', r'解读', r'评估', r'对比', r'比较', r'统计'],
        'summarize': [r'总结', r'概括', r'归纳', r'提炼', r'要点'],
        'chat': [r'你好', r'嗨', r'在吗', r'早上好', r'晚上好'],
        'command': [r'仪表盘', r'设置', r'自检', r'架构', r'工作区', r'备份'],
        'search': [r'搜索', r'关联搜索', r'\d+跳关联', r'全局搜索'],
        'correct': [r'纠正', r'修正', r'更正', r'纠错'],
        'recommend': [r'推荐', r'相关', r'还有什么'],
        'trace': [r'追溯', r'来源', r'出处'],
    }

    @classmethod
    def detect(cls, text: str) -> Tuple[str, float, Dict[str, float]]:
        """检测文本体裁 — 返回 (genre, confidence, scores)"""
        if not text or len(text.strip()) < 2:
            return ('knowledge', 0.0, {})

        # 短文本回退
        if len(text.strip()) < 10:
            return ('knowledge', 0.0, {})

        scores = {}
        for genre, keywords in cls.GENRE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            scores[genre] = score

        total = sum(scores.values())
        if total == 0:
            return ('knowledge', 0.0, scores)

        # 找最高分
        best_genre = max(scores, key=scores.get)
        confidence = scores[best_genre] / total if total > 0 else 0.0

        # 低置信度回退
        if confidence < 0.3 and scores[best_genre] < 2:
            return ('knowledge', confidence, scores)

        return (best_genre, confidence, scores)

    @classmethod
    def classify(cls, text: str, scene: str = None) -> Tuple[str, List[str]]:
        """向后兼容 — 返回 (genre, tags)"""
        genre, _, _ = cls.detect(text)
        kws = _extract_keywords(text)
        tags = list(set(kws))[:5]
        if scene and scene not in tags:
            tags.insert(0, scene)
        return (genre, tags)

    @classmethod
    def classify_v2(cls, text: str, scene: str = None) -> Tuple[str, List[str], str, str, float]:
        """统一管线 — 返回 (genre, tags, action_intent, content_intent, confidence)

        5个维度：
          genre          — 体裁（8种）
          tags           — 领域标签
          action_intent  — 功能路由意图（learn/query/analyze/summarize/chat/command/search/correct/recommend/trace）
          content_intent — 内容意图
          confidence     — 置信度
        """
        genre, confidence, scores = cls.detect(text)
        kws = _extract_keywords(text)
        tags = list(set(kws))[:5]
        if scene and scene not in tags:
            tags.insert(0, scene)

        # 功能路由意图
        action = 'chat'
        for act, patterns in cls.ACTION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    action = act
                    break
            if action != 'chat':
                break

        # 内容意图
        content_intent = 'general'
        if any(kw in text for kw in ['数据', '数字', '统计', '%', '增长', '下降']):
            content_intent = 'data'
        elif any(kw in text for kw in ['原因', '因为', '导致', '所以']):
            content_intent = 'causal'
        elif any(kw in text for kw in ['步骤', '流程', '方法', '如何']):
            content_intent = 'procedural'
        elif any(kw in text for kw in ['定义', '概念', '是什么']):
            content_intent = 'definitional'

        return (genre, tags, action, content_intent, confidence)

    @classmethod
    def extract_skeleton(cls, text: str, genre: str) -> Dict:
        """骨架提取"""
        skeleton = {'type': genre, 'raw_text': text}

        if genre == 'process':
            steps = re.split(r'(?:第一步|第二步|首先|然后|接着|最后|之后)[：:,，]?', text)
            skeleton['steps'] = [s.strip() for s in steps if s.strip()]

        elif genre == 'definition':
            parts = re.split(r'[，,；;]', text)
            skeleton['definitions'] = [p.strip() for p in parts if p.strip()]
            skeleton['main_term'] = parts[0].strip() if parts else ''

        elif genre == 'argument':
            reasons = []
            conclusions = []
            for sent in re.split(r'[。.！!]', text):
                sent = sent.strip()
                if any(kw in sent for kw in ['因为', '由于', '既然']):
                    reasons.append(sent)
                if any(kw in sent for kw in ['所以', '因此', '从而', '导致']):
                    conclusions.append(sent)
            skeleton['reasons'] = reasons
            skeleton['conclusions'] = conclusions

        elif genre == 'data_summary':
            numbers = re.findall(r'[\d.]+[%亿元万亿]', text)
            skeleton['data_points'] = numbers

        return skeleton


# ============================================================
# KnowledgeInferrer — 知识推论引擎
# ============================================================

class KnowledgeInferrer:
    """知识推论引擎 — 因果链提取 + 事实提取 + 推论生成"""

    CAUSAL_PATTERNS = [
        (r'因为(.+?)(?:所以|导致|使得)(.+?)(?:[。.]|$)', 'cause', 'effect'),
        (r'由于(.+?)(?:所以|导致|使得|因此)(.+?)(?:[。.]|$)', 'cause', 'effect'),
        (r'(.+?)导致(.+?)(?:[。.]|$)', 'cause', 'effect'),
        (r'(.+?)使得(.+?)(?:[。.]|$)', 'cause', 'effect'),
        (r'(.+?)从而(.+?)(?:[。.]|$)', 'cause', 'effect'),
        (r'如果(.+?)那么(.+?)(?:[。.]|$)', 'condition', 'consequence'),
        (r'只要(.+?)就(.+?)(?:[。.]|$)', 'condition', 'consequence'),
    ]

    @classmethod
    def extract_causal_links(cls, text: str) -> List[Dict]:
        """因果链提取"""
        links = []
        for pattern, cause_label, effect_label in cls.CAUSAL_PATTERNS:
            for match in re.finditer(pattern, text):
                groups = match.groups()
                if len(groups) >= 2:
                    links.append({
                        'cause': groups[0].strip(),
                        'effect': groups[1].strip(),
                        'type': cause_label,
                    })
        return links

    @classmethod
    def infer(cls, text: str) -> Dict:
        """推论生成"""
        facts = []
        causal_links = cls.extract_causal_links(text)

        # 提取事实
        sentences = re.split(r'[。.!！]', text)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 5:
                facts.append(sent)

        # 生成推论
        summary = ""
        if causal_links:
            summary = f"检测到因果链{len(causal_links)}条，"
            for link in causal_links[:3]:
                summary += f"「{link['cause']}」→「{link['effect']}」；"
        elif facts:
            summary = f"提取{len(facts)}条事实信息"

        return {
            'facts': facts,
            'causal_links': causal_links,
            'summary': summary,
            'inferences': [],
        }


# ============================================================
# DeepReason — 深度推理引擎
# ============================================================

class DeepReason:
    """深度推理引擎 — 查询分类 + 推理指令生成"""

    QUERY_TYPES = {
        'data_analysis': ['分析', '统计', '数据', '趋势', '对比', '比较', '指标'],
        'summarize': ['总结', '概括', '归纳', '提炼', '要点', '摘要'],
        'inference': ['推断', '推测', '预测', '估计', '预计', '趋势'],
        'comparison': ['比较', '对比', '区别', '差异', '优劣', '哪个好'],
        'composition': ['写', '撰写', '创作', '起草', '作文', '文章'],
        'general_query': [],
    }

    @classmethod
    def classify_query(cls, text: str) -> List[str]:
        """查询类型分类"""
        types = []
        for qtype, keywords in cls.QUERY_TYPES.items():
            if any(kw in text for kw in keywords):
                types.append(qtype)
        if not types:
            types.append('general_query')
        return types

    @classmethod
    def generate_instruction(cls, text: str) -> Dict:
        """生成深度推理指令"""
        types = cls.classify_query(text)
        instruction = "深度推理指令："

        if 'data_analysis' in types:
            instruction += "提取数据指标、分析趋势变化、对比关键数据点"
        elif 'summarize' in types:
            instruction += "提炼核心结论、提取关键论据、标注数据支撑"
        elif 'inference' in types:
            instruction += "基于已知信息进行逻辑推演、识别因果关系、预测发展趋势"
        elif 'comparison' in types:
            instruction += "从多个维度进行对比分析、突出差异点和共同点"
        elif 'composition' in types:
            instruction += "根据主题组织结构、填充论据、确保逻辑连贯"
        else:
            instruction += "理解用户意图、检索相关知识、生成准确回答"

        return {'types': types, 'instruction': instruction}


# ============================================================
# ContextMemoryLayer — 三层上下文记忆
# ============================================================

class ContextMemoryLayer:
    """三层上下文记忆层 — 短程/中程/长程 + SimHash语义匹配"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.sessions_file = self.data_dir / "context_sessions.json"
        self.topics_file = self.data_dir / "context_topics.json"
        self.sessions = []
        self.topics = {}
        self._load()

    def _load(self):
        try:
            if self.sessions_file.exists():
                with open(self.sessions_file, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            if self.topics_file.exists():
                with open(self.topics_file, "r", encoding="utf-8") as f:
                    self.topics = json.load(f)
        except Exception:
            pass

    def _save(self):
        try:
            self.data_dir.mkdir(exist_ok=True)
            with open(self.sessions_file, "w", encoding="utf-8") as f:
                json.dump(self.sessions[-500:], f, ensure_ascii=False)
            with open(self.topics_file, "w", encoding="utf-8") as f:
                json.dump(self.topics, f, ensure_ascii=False)
        except Exception:
            pass

    @staticmethod
    def _simhash(text: str) -> int:
        return _simhash(text)

    def save_session(self, keyword: str, context: Dict):
        """短程：保存对话上下文"""
        sh = _simhash(keyword)
        self.sessions.append({
            'keyword': keyword,
            'simhash': sh,
            'entities': context.get('entities', []),
            'injection': context.get('injection', ''),
            'timestamp': datetime.now().isoformat(),
        })
        if len(self.sessions) > 1000:
            self.sessions = self.sessions[-500:]
        self._save()

    def get_last_context(self, keyword: str) -> Dict:
        """获取最近上下文（SimHash语义匹配）"""
        if not self.sessions:
            return {'found': False}

        query_sh = _simhash(keyword)
        best_match = None
        best_dist = float('inf')

        # 精确匹配
        for session in reversed(self.sessions):
            if session.get('keyword') == keyword:
                return {
                    'found': True,
                    'previous_keyword': session['keyword'],
                    'entities': session.get('entities', []),
                    'injection': session.get('injection', ''),
                    'method': 'exact',
                }

        # SimHash 语义匹配（海明距离 ≤ 8 视为相似）
        for session in reversed(self.sessions[-50:]):
            dist = _simhash_distance(query_sh, session.get('simhash', 0))
            if dist < best_dist:
                best_dist = dist
                best_match = session

        if best_match and best_dist <= 8:
            return {
                'found': True,
                'previous_keyword': best_match['keyword'],
                'entities': best_match.get('entities', []),
                'injection': best_match.get('injection', ''),
                'method': f'simhash(d={best_dist})',
            }

        return {'found': False}

    def inherit_context(self, keyword: str, prev_context: Dict) -> str:
        """上下文继承"""
        if not prev_context.get('found'):
            return ""
        entities = prev_context.get('entities', [])
        if entities:
            return f"继承上下文：{'、'.join(entities[:5])}"
        return ""

    def check_topic_continuation(self, prev_keyword: str, current_keyword: str) -> Dict:
        """话题延续检测"""
        if not prev_keyword or not current_keyword:
            return {'is_continuation': False, 'similarity': 0}

        # 关键词重叠
        prev_kws = set(_extract_keywords(prev_keyword))
        curr_kws = set(_extract_keywords(current_keyword))
        overlap = prev_kws & curr_kws
        keyword_overlap = len(overlap) / max(len(prev_kws | curr_kws), 1)

        # SimHash 相似度
        sh1 = _simhash(prev_keyword)
        sh2 = _simhash(current_keyword)
        hamming = _simhash_distance(sh1, sh2)
        simhash_sim = 1 - hamming / 64

        # 综合判断
        is_continuation = keyword_overlap > 0.3 or simhash_sim > 0.7
        return {
            'is_continuation': is_continuation,
            'keyword_overlap': keyword_overlap,
            'simhash_similarity': simhash_sim,
            'similarity': max(keyword_overlap, simhash_sim),
        }

    def merge_topic(self, keyword: str, context: Dict) -> Dict:
        """中程+长程：主题合并"""
        # 提取 topic（前4个中文字符或英文词）
        topic = keyword[:4] if keyword else "unknown"
        if topic not in self.topics:
            self.topics[topic] = {
                'keywords': [keyword],
                'entities': context.get('entities', []),
                'injections': [context.get('injection', '')],
                'count': 1,
                'last_updated': datetime.now().isoformat(),
            }
        else:
            self.topics[topic]['keywords'].append(keyword)
            if context.get('injection'):
                self.topics[topic]['injections'].append(context['injection'])
            self.topics[topic]['count'] += 1
            self.topics[topic]['last_updated'] = datetime.now().isoformat()

        unique_kws = len(set(self.topics[topic]['keywords']))
        self._save()
        return {'topic': topic, 'total_count': self.topics[topic]['count'],
                'unique_keywords': unique_kws}

    def get_merged(self, topic: str) -> str:
        """获取聚合知识"""
        if topic not in self.topics:
            return ""
        data = self.topics[topic]
        lines = [f"主题「{topic}」({data['count']}条知识)"]
        for inj in data.get('injections', [])[-5:]:
            lines.append(f"  - {inj}")
        return "\n".join(lines)

    def stat(self) -> Dict:
        """统计信息"""
        return {
            'sessions': len(self.sessions),
            'topic_merges': len(self.topics),
            'topics': list(self.topics.keys()),
        }


# ============================================================
# DataAnalyzer — 数据分析引擎
# ============================================================

class DataAnalyzer:
    """数据分析引擎 — 数字提取 + 趋势分析"""

    @classmethod
    def analyze(cls, text: str) -> Dict:
        """数据分析"""
        numbers = re.findall(r'[\d.]+%?|[\d.]+[亿元万亿]?|[-]?\d+', text)

        result = {
            'has_data': len(numbers) > 0,
            'numbers': numbers,
            'numbers_count': len(numbers),
            'trends': [],
            'comparisons': [],
        }

        # 趋势检测
        trend_keywords = {
            'increase': ['增长', '上升', '提高', '增加', '提升', '同比'],
            'decrease': ['下降', '减少', '降低', '下滑', '回落'],
            'stable': ['持平', '不变', '稳定', '维持'],
        }

        for direction, keywords in trend_keywords.items():
            for kw in keywords:
                if kw in text:
                    # 找附近数字
                    idx = text.find(kw)
                    nearby = text[max(0, idx-10):idx+len(kw)+10]
                    nums = re.findall(r'[\d.]+%?', nearby)
                    if nums:
                        result['trends'].append({
                            'direction': direction,
                            'keyword': kw,
                            'values': nums,
                        })

        # 对比检测
        if any(kw in text for kw in ['对比', '比较', 'vs', 'VS', '其中']):
            all_nums = re.findall(r'[\d.]+%?', text)
            if len(all_nums) >= 2:
                result['comparisons'] = all_nums[:5]

        return result


# ============================================================
# Summarizer — 文章总结引擎
# ============================================================

class Summarizer:
    """文章总结引擎 — 章节检测 + 关键点提取"""

    @classmethod
    def summarize(cls, text: str) -> Dict:
        """文章总结"""
        result = {
            'summary': '',
            'key_points': [],
            'sections': [],
            'word_count': len(text),
        }

        if not text.strip():
            return result

        # 章节检测
        section_pattern = r'^(#{1,4}\s+.+|第[一二三四五六七八九十\d]+[章节部分]|[一二三四五六七八九十]+[、.])\s*(.*)$'
        sections = []
        current_section = {'title': '引言', 'content': ''}

        for line in text.split('\n'):
            m = re.match(section_pattern, line.strip())
            if m:
                if current_section['content'].strip():
                    sections.append(dict(current_section))
                current_section = {'title': m.group(1).strip(), 'content': m.group(2) if m.group(2) else ''}
            else:
                current_section['content'] += line + '\n'

        if current_section['content'].strip():
            sections.append(dict(current_section))

        result['sections'] = [{'title': s['title'], 'length': len(s['content'])} for s in sections]

        # 关键点提取
        sentences = re.split(r'[。.!！\n]', text)
        key_points = []
        conclusion_markers = ['总之', '综上', '因此', '结果表明', '研究发现',
                             '需要注意的是', '关键', '核心', '重要', '主要']
        data_markers = ['达到', '提高', '降低', '增长', '减少', '%', '亿', '万']
        example_markers = ['例如', '比如', '如', '举例']

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue
            # 结论类
            if any(m in sent for m in conclusion_markers):
                key_points.append(sent)
            # 数据类
            elif any(m in sent for m in data_markers) and re.search(r'\d', sent):
                key_points.append(sent)
            # 短文本，取前几条
            if len(key_points) >= 10:
                break

        result['key_points'] = key_points[:10]

        # 生成摘要
        if key_points:
            result['summary'] = '。'.join(key_points[:5]) + '。'
        else:
            first_n = sentences[:3]
            result['summary'] = '。'.join(s.strip() for s in first_n if s.strip()) + '。'

        return result


# ============================================================
# MemoryEngine — 核心知识图谱记忆引擎
# ============================================================

class MemoryEngine:
    """核心记忆引擎 — 知识图谱 + SimHash检索 + 图扩散搜索 + 自动建边"""

    # 自动纠错词典
    CORRECTIONS = {
        '派森': 'Python', '物连网': '物联网', '人工只能': '人工智能',
        '机器语': '机器语言', '加归': '归一化', '卷极': '卷积',
        '深度学习算法': '深度学习', 'AI大模': 'AI大模型',
    }

    # 关系检测词
    RELATION_WORDS = {
        '同义': ['也叫', '又称', '别名', '同义词', '即', '也就是'],
        '相关': ['相关', '关联', '涉及', '包括', '包含'],
        '因果': ['因为', '导致', '所以', '由于', '原因'],
        '对比': ['区别', '差异', '对比', '不同', '比较'],
        '层级': ['属于', '包含于', '子类', '父类', '上位', '下位'],
        '序列': ['然后', '之后', '接着', '首先', '最后'],
        '相似': ['类似', '相似', '像', '仿佛', '好比'],
    }

    # 种子知识
    SEED_KNOWLEDGE = [
        ("Python是一种高级编程语言，广泛用于数据科学、AI开发和Web开发", "技术"),
        ("机器学习是AI的子领域，通过数据训练模型使计算机自动学习和改进", "技术"),
        ("深度学习是机器学习的子集，使用神经网络处理复杂数据模式", "技术"),
        ("数据库是按照数据结构组织、存储和管理数据的仓库", "技术"),
        ("API（Application Programming Interface）是应用程序编程接口", "技术"),
        ("Git是分布式版本控制系统，用于跟踪代码变更和团队协作", "工具"),
        ("HTTP是超文本传输协议，是Web通信的基础", "技术"),
        ("Docker是容器化平台，用于打包和部署应用程序", "工具"),
    ]

    def __init__(self, data_dir: Path = None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.data_file = self.data_dir / "memory_duck_data.json"
        self.db_path = self.data_dir / "left_brain.db"

        self.nodes: List[Optional[Dict]] = []
        self.hash_index: Dict[int, int] = {}
        self.simhash_index: Dict[int, int] = {}
        self._kw_index: Dict[str, List[int]] = {}
        self.workspace: str = "global"
        self.current_session_id: str = _new_session_id()

        self.learn_count = 0
        self.query_count = 0
        self.search_count = 0
        self.token_savings = 0

        self.context_stack = _ContextStack()
        self._context_memory = ContextMemoryLayer(self.data_dir)
        self._auto_perceive = True

        self._bitmap_size = 1024 * 8

        self._load()

    def _load(self):
        """从磁盘加载数据"""
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.nodes = data.get("nodes", [])
            self._bitmap_size = data.get("bitmap_size", 1024 * 8)
            self.learn_count = data.get("learn_count", 0)
            self.query_count = data.get("query_count", 0)
            self.search_count = data.get("search_count", 0)
            self.token_savings = data.get("token_savings", 0)
            self.workspace = data.get("current_workspace", "global")
            self._auto_perceive = data.get("auto_perceive", True)
            self._rebuild_index()
        except Exception:
            pass

    def _rebuild_index(self):
        """重建索引"""
        self.hash_index.clear()
        self.simhash_index.clear()
        self._kw_index.clear()
        for i, node in enumerate(self.nodes):
            if not isinstance(node, dict) or not node.get("text"):
                continue
            ws = node.get("workspace", "global")
            text = node.get("text", "")
            h = _hash_64(f"{ws}:{text}")
            self.hash_index[h] = i
            sh = _simhash(text)
            self.simhash_index[sh] = i
            self._keyword_index_add(text, i)

    def _keyword_index_add(self, text: str, index: int):
        """添加关键词索引"""
        kws = _extract_keywords(text)
        for kw in kws:
            if kw not in self._kw_index:
                self._kw_index[kw] = []
            if index not in self._kw_index[kw]:
                self._kw_index[kw].append(index)

    def _save(self):
        """保存数据到磁盘"""
        try:
            self.data_dir.mkdir(exist_ok=True)
            data = {
                'version': VERSION,
                'bitmap_size': self._bitmap_size,
                'nodes': self.nodes,
                'learn_count': self.learn_count,
                'query_count': self.query_count,
                'search_count': self.search_count,
                'token_savings': self.token_savings,
                'current_workspace': self.workspace,
                'auto_perceive': self._auto_perceive,
                'updated_at': datetime.now().isoformat(),
            }
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._sync_memory_md()
        except Exception:
            pass

    def _sync_memory_md(self):
        """同步 memory markdown（简化版）"""
        try:
            valid = [n for n in self.nodes if isinstance(n, dict) and n.get("text")]
            total = len(valid)
            if total == 0:
                return
            lines = [f"你在当前工作区积累了 {total} 条知识（全局共 {total} 条）。"]
            INJECT_FILE.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass

    # ===== 节点操作 =====

    def add_node(self, text: str, category: str = "通用",
                 workspace: str = None, genre: str = "",
                 skeleton: str = "", domain: str = "",
                 source_context: str = "", source_turn_index: int = -1,
                 source: str = "") -> int:
        """添加知识节点，返回索引"""
        if not text or not text.strip():
            return -1

        ws = workspace or self.workspace
        now = time.time()
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        sid = self.current_session_id

        # 检查是否已存在（去重）
        existing = self.find_node(text[:30], workspace=ws)
        if existing is not None:
            return existing

        node = {
            'text': text.strip(),
            'category': category or "通用",
            'workspace': ws,
            'strength': 100,
            'edges': [],
            'source': source,
            'created_at': now,
            'updated_at': now,
            'last_accessed': now,
            'access_count': 0,
            'learned_at': now_iso,
            'updated_at_iso': now_iso,
            'last_accessed_at': now_iso,
            'session_id': sid,
            'updated_by_session': '',
        }
        # v3.8 新增字段（非空才写入）
        if genre:
            node['genre'] = genre
        if skeleton:
            node['skeleton'] = skeleton
        if domain:
            node['domain'] = domain
        if source_context:
            node['source_context'] = source_context
        if source_turn_index >= 0:
            node['source_turn_index'] = source_turn_index

        # 找到第一个空位或追加
        idx = -1
        for i, n in enumerate(self.nodes):
            if n is None:
                idx = i
                break
        if idx == -1:
            idx = len(self.nodes)
            self.nodes.append(node)
        else:
            self.nodes[idx] = node

        # 建索引
        h = _hash_64(f"{ws}:{text.strip()}")
        self.hash_index[h] = idx
        sh = _simhash(text.strip())
        self.simhash_index[sh] = idx
        self._keyword_index_add(text.strip(), idx)

        self.learn_count += 1
        self._save()
        return idx

    def find_node(self, keyword: str, workspace: str = None,
                  genre_aware: bool = False) -> Optional[int]:
        """查找知识节点（多路检索）"""
        if not keyword:
            return None
        self.query_count += 1
        ws = workspace or self.workspace

        # 第1路：精确 hash 匹配
        h = _hash_64(f"{ws}:{keyword}")
        if h in self.hash_index:
            return self.hash_index[h]

        # 第2路：关键词索引
        kws = _extract_keywords(keyword)
        best_idx = None
        best_score = 0
        for kw in kws:
            if kw in self._kw_index:
                for idx in self._kw_index[kw]:
                    if idx >= len(self.nodes) or not isinstance(self.nodes[idx], dict):
                        continue
                    node = self.nodes[idx]
                    if ws != "global" and node.get("workspace", "global") != ws and node.get("workspace", "global") != "global":
                        continue
                    score = sum(1 for k in kws if k in node.get("text", ""))
                    if score > best_score:
                        best_score = score
                        best_idx = idx
        if best_idx is not None:
            self._touch_node(best_idx)
            return best_idx

        # 第3路：SimHash 语义匹配
        query_sh = _simhash(keyword)
        best_dist = float('inf')
        for sh, idx in self.simhash_index.items():
            if idx >= len(self.nodes) or not isinstance(self.nodes[idx], dict):
                continue
            node = self.nodes[idx]
            if ws != "global" and node.get("workspace", "global") != ws and node.get("workspace", "global") != "global":
                continue
            dist = _simhash_distance(query_sh, sh)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx is not None and best_dist <= 12:
            self._touch_node(best_idx)
            return best_idx

        # 第4路：子串匹配
        for i, node in enumerate(self.nodes):
            if not isinstance(node, dict) or not node.get("text"):
                continue
            if ws != "global" and node.get("workspace", "global") != ws and node.get("workspace", "global") != "global":
                continue
            if keyword in node.get("text", ""):
                self._touch_node(i)
                return i

        # 第5路：全文搜索
        for i, node in enumerate(self.nodes):
            if not isinstance(node, dict) or not node.get("text"):
                continue
            node_kws = set(_extract_keywords(node.get("text", "")))
            query_kws_set = set(kws)
            overlap = len(node_kws & query_kws_set)
            if overlap >= max(1, len(kws) // 2):
                self._touch_node(i)
                return i

        # 第6路：体裁感知检索
        if genre_aware:
            query_genre, _, _ = GenreClassifier.detect(keyword)
            genre_best = None
            genre_best_score = 0
            for i, node in enumerate(self.nodes):
                if not isinstance(node, dict) or not node.get("text"):
                    continue
                node_genre = node.get("genre", "")
                if node_genre == query_genre:
                    # 同体裁加分
                    node_kws = set(_extract_keywords(node.get("text", "")))
                    overlap = len(node_kws & set(kws))
                    if overlap > genre_best_score:
                        genre_best_score = overlap
                        genre_best = i
            if genre_best is not None:
                self._touch_node(genre_best)
                return genre_best

        return None

    def _touch_node(self, idx: int):
        """更新节点的访问时间和计数"""
        if 0 <= idx < len(self.nodes) and isinstance(self.nodes[idx], dict):
            now = time.time()
            self.nodes[idx]['last_accessed'] = now
            self.nodes[idx]['last_accessed_at'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            self.nodes[idx]['access_count'] = self.nodes[idx].get('access_count', 0) + 1

    # ===== 搜索 =====

    def search(self, keyword: str, max_hops: int = 2,
               workspace: str = None) -> Dict:
        """图扩散搜索"""
        self.search_count += 1
        ws = workspace or self.workspace
        results = []

        start_idx = self.find_node(keyword, workspace=ws)
        if start_idx is None:
            return {'status': 'not_found', 'keyword': keyword, 'details': []}

        visited = {start_idx}
        queue = [(start_idx, 0)]

        while queue:
            idx, hop = queue.pop(0)
            if hop > max_hops:
                continue
            node = self.nodes[idx]
            if not isinstance(node, dict):
                continue

            # 提取关系
            for edge in node.get("edges", []):
                target, relation = self._parse_edge(edge)
                if target is None or target >= len(self.nodes) or not isinstance(self.nodes[target], dict):
                    continue
                if target in visited:
                    continue
                visited.add(target)

                target_node = self.nodes[target]
                self._touch_node(target)
                results.append({
                    'hop': hop + 1,
                    'index': target,
                    'text': target_node.get("text", ""),
                    'category': target_node.get("category", ""),
                    'relation': relation,
                    'workspace': target_node.get("workspace", ""),
                })
                queue.append((target, hop + 1))

        self.token_savings += len(results) * 50

        return {
            'status': 'ok',
            'keyword': keyword,
            'start': start_idx,
            'details': results,
            'total': len(results),
        }

    def _parse_edge(self, edge):
        """解析边格式"""
        if isinstance(edge, int):
            return edge, "related"
        elif isinstance(edge, dict):
            return edge.get("target", -1), edge.get("relation", "related")
        elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
            return edge[0], edge[1]
        elif isinstance(edge, (list, tuple)) and len(edge) == 1:
            return edge[0], "related"
        return None, ""

    # ===== 学习与提取 =====

    def learn_from_content(self, text: str) -> Dict:
        """从内容学习知识 + 自动建边"""
        if not text or not text.strip():
            return {'status': 'empty', 'learned': [], 'auto_edges': 0}

        # 体裁分析
        genre, tags, action, content_intent, conf = GenreClassifier.classify_v2(text)

        # 提取知识条目
        learned = []
        sentences = re.split(r'[。.!！\n]', text)
        added_indices = []

        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 5:
                continue

            # 判断是否值得学习（具体事实 > 模糊观点）
            is_fact = bool(re.search(r'\d', sent) or
                          any(kw in sent for kw in ['是', '指', '定义', '为', '有', '在',
                                                     '叫做', '等于', '包括', '分为']))

            if not is_fact:
                continue

            idx = self.add_node(sent, category=tags[0] if tags else "通用",
                               genre=genre,
                               domain=tags[0] if tags else "")
            if idx >= 0:
                added_indices.append(idx)
                learned.append({
                    'index': idx,
                    'text': sent[:80],
                    'genre': genre,
                    'category': tags[0] if tags else "通用",
                })

        # 自动建边
        auto_edges = 0
        if added_indices:
            auto_edges = self._auto_build_edges(added_indices)

        # 写入三层上下文
        if added_indices:
            self._write_context_layers(text[:30], 'learn', {'learned': learned})

        return {
            'status': 'ok',
            'learned': learned,
            'nodes_added': len(learned),
            'auto_edges': auto_edges,
            'genre': genre,
        }

    def _auto_build_edges(self, new_indices: List[int]) -> int:
        """自动建边 — 检测新节点与已有节点的关联"""
        if not new_indices:
            return 0
        total_nodes = len([n for n in self.nodes if isinstance(n, dict) and n.get("text")])
        if total_nodes > 500:
            return 0

        edges_added = 0
        max_edges_per_run = 20
        max_checks = 300
        checks = 0

        for new_idx in new_indices:
            if new_idx < 0 or new_idx >= len(self.nodes):
                continue
            new_node = self.nodes[new_idx]
            if not isinstance(new_node, dict):
                continue

            for i, node in enumerate(self.nodes):
                if checks >= max_checks or edges_added >= max_edges_per_run:
                    return edges_added
                if i == new_idx or not isinstance(node, dict) or not node.get("text"):
                    continue
                checks += 1

                relation = self.detect_relation(new_node, node)
                if relation and relation != "未知":
                    self.add_edge(new_idx, i, relation)
                    edges_added += 1

        return edges_added

    def detect_relation(self, node_a: Dict, node_b: Dict) -> str:
        """检测两个节点之间的关系"""
        if not isinstance(node_a, dict) or not isinstance(node_b, dict):
            return "未知"

        text_a = node_a.get("text", "")
        text_b = node_b.get("text", "")

        # 同义关系
        for kw in self.RELATION_WORDS['同义']:
            if kw in text_a or kw in text_b:
                # 检查是否互指
                return "同义"

        # 关键词重叠
        kws_a = set(_extract_keywords(text_a))
        kws_b = set(_extract_keywords(text_b))
        overlap = kws_a & kws_b

        if not overlap:
            return "未知"

        overlap_ratio = len(overlap) / max(len(kws_a | kws_b), 1)

        # 因果关系
        for kw in self.RELATION_WORDS['因果']:
            if kw in f"{text_a} {text_b}":
                return "因果"

        # 层级关系
        for kw in self.RELATION_WORDS['层级']:
            if kw in f"{text_a} {text_b}":
                return "层级"

        # 对比关系
        for kw in self.RELATION_WORDS['对比']:
            if kw in f"{text_a} {text_b}":
                return "对比"

        # 相似关系
        if overlap_ratio > 0.5:
            return "相关"

        if overlap_ratio > 0.2:
            return "弱相关"

        return "未知"

    def add_edge(self, from_idx: int, to_idx: int, relation: str = "related"):
        """添加边"""
        if from_idx < 0 or from_idx >= len(self.nodes):
            return
        if to_idx < 0 or to_idx >= len(self.nodes):
            return

        node = self.nodes[from_idx]
        if not isinstance(node, dict):
            return

        # 检查边是否已存在
        for edge in node.get("edges", []):
            target, _ = self._parse_edge(edge)
            if target == to_idx:
                return

        if "edges" not in node:
            node["edges"] = []
        node["edges"].append({"target": to_idx, "relation": relation})

        # 双向边（因果和层级除外）
        if relation not in ("因果",):
            target_node = self.nodes[to_idx]
            if isinstance(target_node, dict):
                if "edges" not in target_node:
                    target_node["edges"] = []
                # 检查是否已存在反向边
                for edge in target_node.get("edges", []):
                    t, _ = self._parse_edge(edge)
                    if t == from_idx:
                        self._save()
                        return
                target_node["edges"].append({"target": from_idx, "relation": relation})

        self._save()

    # ===== 注入 =====

    def inject(self, content: str = "", **kwargs) -> Dict:
        """注入相关知识到上下文"""
        if not content:
            return {'status': 'empty', 'injected': 0, 'results': []}

        kws = _extract_keywords(content)
        results = []
        injected_count = 0

        for kw in kws[:5]:
            idx = self.find_node(kw)
            if idx is not None and isinstance(self.nodes[idx], dict):
                node = self.nodes[idx]
                results.append({
                    'keyword': kw,
                    'text': node.get('text', ''),
                    'category': node.get('category', ''),
                    'access_count': node.get('access_count', 0),
                })
                injected_count += 1

        # SimHash 补充
        if injected_count == 0:
            query_sh = _simhash(content)
            for sh, idx in self.simhash_index.items():
                if idx >= len(self.nodes) or not isinstance(self.nodes[idx], dict):
                    continue
                if _simhash_distance(query_sh, sh) <= 8:
                    node = self.nodes[idx]
                    results.append({
                        'keyword': content[:20],
                        'text': node.get('text', ''),
                        'category': node.get('category', ''),
                        'method': 'simhash',
                    })
                    injected_count += 1
                    break

        if injected_count > 0:
            self.token_savings += injected_count * 100

        return {
            'status': 'ok' if injected_count > 0 else 'not_found',
            'injected': injected_count,
            'results': results,
        }

    # ===== Session =====

    def session(self, **kwargs) -> Dict:
        """会话初始化 — 返回完整上下文摘要"""
        self.current_session_id = _new_session_id()

        valid = [n for n in self.nodes if isinstance(n, dict) and n.get("text")]
        total = len(valid)

        # 分类统计
        cat_counter = Counter(n.get("category", "未分类") for n in valid)
        category_summary = [
            {"category": cat, "count": cnt}
            for cat, cnt in cat_counter.most_common(5)
        ]

        # 高频知识
        high_freq = sorted(valid, key=lambda n: n.get("access_count", 0), reverse=True)[:5]
        high_freq_knowledge = [
            {"text": n.get("text", ""), "access_count": n.get("access_count", 0)}
            for n in high_freq
        ]

        # 最近学习
        recent = sorted(valid, key=lambda n: str(n.get("learned_at", "")), reverse=True)[:5]
        recent_knowledge = [
            {"text": n.get("text", ""), "learned_at": n.get("learned_at", "")}
            for n in recent
        ]

        # 最近更新
        updated = sorted(valid, key=lambda n: str(n.get("updated_at_iso", "")), reverse=True)[:3]
        recent_updated = [
            {"text": n.get("text", ""), "updated_at": n.get("updated_at_iso", "")}
            for n in updated
        ]

        # 工作区分布
        ws_counter = Counter(n.get("workspace", "global") for n in valid)
        workspace_distribution = dict(ws_counter)

        summary = {
            'workspace': self.workspace,
            'session_id': self.current_session_id,
            'total_knowledge': total,
            'category_summary': category_summary,
            'high_freq_knowledge': high_freq_knowledge,
            'recent_knowledge': recent_knowledge,
            'recent_updated': recent_updated,
            'workspace_distribution': workspace_distribution,
        }

        self._save()
        return summary

    # ===== 统一管线 =====

    def auto_process_v2(self, text: str, **kwargs) -> Dict:
        """统一管线 — 意图分类 + 自动处理"""
        genre, tags, action, content_intent, conf = GenreClassifier.classify_v2(text)
        result = {
            'intent': action,
            'genre': genre,
            'tags': tags,
            'content_intent': content_intent,
            'confidence': conf,
        }

        if action == 'learn':
            learn_result = self.learn_from_content(text)
            result['learned'] = learn_result.get('learned', [])
            result['nodes_added'] = learn_result.get('nodes_added', 0)
            result['auto_edges'] = learn_result.get('auto_edges', 0)
        elif action == 'query':
            idx = self.find_node(text)
            if idx is not None and isinstance(self.nodes[idx], dict):
                result['found'] = True
                result['result'] = self.nodes[idx].get('text', '')
            else:
                result['found'] = False
        elif action == 'analyze':
            result['analysis'] = DataAnalyzer.analyze(text)
        elif action == 'summarize':
            result['summary'] = Summarizer.summarize(text)
        elif action == 'correct':
            result.update(self.correct(text))
        elif action == 'search':
            result['search'] = self.search(text)
        elif action == 'recommend':
            search_result = self.search(text, max_hops=2)
            result['recommendations'] = search_result.get('details', [])
        elif action == 'trace':
            result.update(self.trace_source_context(text))

        return result

    # ===== 纠错 =====

    def correct(self, text: str) -> Dict:
        """智能纠错"""
        corrected = text
        changed = False
        corrections = []

        for wrong, right in self.CORRECTIONS.items():
            if wrong in corrected:
                corrected = corrected.replace(wrong, right)
                corrections.append({'wrong': wrong, 'right': right})
                changed = True

        return {'changed': changed, 'original': text, 'corrected': corrected,
                'corrections': corrections}

    # ===== 追溯来源 =====

    def trace_source_context(self, keyword: str) -> Dict:
        """追溯知识来源 + 因果链可视化 + 时间线"""
        idx = self.find_node(keyword)
        if idx is None:
            return {'status': 'not_found', 'keyword': keyword}

        node = self.nodes[idx]
        causal_links = KnowledgeInferrer.extract_causal_links(node.get("text", ""))
        genre = node.get("genre", "")

        # 时间线
        timeline = [{
            'learned_at': node.get('learned_at', ''),
            'updated_at': node.get('updated_at_iso', ''),
            'last_accessed': node.get('last_accessed_at', ''),
            'session_id': node.get('session_id', ''),
            'source_context': node.get('source_context', '')[:200],
        }]

        # 追溯关联节点
        related = []
        for edge in node.get("edges", []):
            target, relation = self._parse_edge(edge)
            if target is not None and 0 <= target < len(self.nodes) and isinstance(self.nodes[target], dict):
                related.append({
                    'text': self.nodes[target].get("text", "")[:80],
                    'relation': relation,
                    'learned_at': self.nodes[target].get("learned_at", ""),
                })

        return {
            'status': 'ok',
            'keyword': keyword,
            'node': {'text': node.get("text", ""), 'category': node.get("category", "")},
            'genre': genre,
            'causal_links': causal_links,
            'timeline': timeline,
            'related': related,
        }

    # ===== 知识管理 =====

    def modify(self, old_text: str, new_text: str, **kwargs) -> Dict:
        """修改已有知识"""
        idx = self.find_node(old_text)
        if idx is None:
            return {'status': 'not_found', 'message': f'未找到包含「{old_text}」的知识'}

        node = self.nodes[idx]
        old = node.get("text", "")
        node['text'] = new_text
        node['updated_at'] = time.time()
        node['updated_at_iso'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        node['updated_by_session'] = self.current_session_id

        # 重建索引
        self._rebuild_index()
        self._save()

        return {'status': 'ok', 'message': f'已修改知识', 'old': old, 'new': new_text}

    def delete(self, keyword: str, **kwargs) -> Dict:
        """删除知识"""
        idx = self.find_node(keyword)
        if idx is None:
            return {'status': 'not_found', 'message': f'未找到包含「{keyword}」的知识'}

        removed = self.nodes[idx]
        self.nodes[idx] = None

        # 清理其他节点指向此节点的边
        for node in self.nodes:
            if not isinstance(node, dict):
                continue
            node['edges'] = [e for e in node.get("edges", [])
                            if self._parse_edge(e)[0] != idx]

        self._rebuild_index()
        self._save()

        return {'status': 'ok', 'message': f'已删除知识', 'removed': removed.get("text", "")}

    def list_knowledge(self, page: int = 1, per_page: int = 10,
                       workspace: str = None) -> Dict:
        """分页列出知识"""
        ws = workspace or self.workspace
        valid = [(i, n) for i, n in enumerate(self.nodes)
                 if isinstance(n, dict) and n.get("text")
                 and (ws == "global" or n.get("workspace", "global") == ws or n.get("workspace", "global") == "global")]

        total = len(valid)
        start = (page - 1) * per_page
        end = start + per_page
        items = valid[start:end]

        result_items = []
        for i, node in items:
            result_items.append({
                'index': i,
                'text': node.get("text", ""),
                'category': node.get("category", ""),
                'workspace': node.get("workspace", ""),
                'access_count': node.get("access_count", 0),
                'learned_at': node.get("learned_at", ""),
            })

        return {
            'status': 'ok',
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': (total + per_page - 1) // per_page,
            'items': result_items,
        }

    # ===== 种子知识 =====

    def seed(self, scope: str = "all") -> Dict:
        """注入种子知识"""
        nodes_added = 0
        edges_added = 0
        added_indices = []

        for text, category in self.SEED_KNOWLEDGE:
            idx = self.add_node(text, category=category, source="seed")
            if idx >= 0:
                nodes_added += 1
                added_indices.append(idx)

        # 建立种子间的关联
        for i in range(len(added_indices)):
            for j in range(i + 1, len(added_indices)):
                if i >= len(self.nodes) or j >= len(self.nodes):
                    continue
                node_a = self.nodes[added_indices[i]]
                node_b = self.nodes[added_indices[j]]
                if not isinstance(node_a, dict) or not isinstance(node_b, dict):
                    continue
                relation = self.detect_relation(node_a, node_b)
                if relation and relation != "未知":
                    self.add_edge(added_indices[i], added_indices[j], relation)
                    edges_added += 1

        self._save()
        return {'status': 'ok', 'message': f'已注入种子知识',
                'nodes_added': nodes_added, 'edges_added': edges_added}

    # ===== 纠缠场 =====

    def entangle(self, keyword: str) -> Dict:
        """纠缠场关联分析"""
        result = self.search(keyword, max_hops=2)
        return result

    # ===== Workspace =====

    def set_workspace(self, path: str) -> Dict:
        """设置工作区"""
        if not path:
            self.workspace = "global"
        else:
            p = Path(path)
            name = p.name
            # 跳过日期目录
            if re.match(r'\d{4}-\d{2}-\d{2}', name):
                name = p.parent.name
            self.workspace = f"ws_{name}"

        self._save()
        return {'status': 'ok', 'workspace': self.workspace}

    def get_workspace_info(self) -> Dict:
        """获取工作区信息"""
        valid = [n for n in self.nodes if isinstance(n, dict) and n.get("text")]
        ws_counts = Counter(n.get("workspace", "global") for n in valid)
        distribution = dict(ws_counts)
        return {
            'current': self.workspace,
            'distribution': distribution,
            'total_nodes': len(valid),
        }

    # ===== 统计 =====

    def stats(self) -> Dict:
        """统计信息"""
        valid = [n for n in self.nodes if isinstance(n, dict) and n.get("text")]
        total = len(valid)
        edges = sum(len(n.get("edges", [])) for n in valid)

        cat_counter = Counter(n.get("category", "未分类") for n in valid)
        ws_counter = Counter(n.get("workspace", "global") for n in valid)

        return {
            'total_knowledge': total,
            'total_edges': edges,
            'learn_count': self.learn_count,
            'query_count': self.query_count,
            'search_count': self.search_count,
            'token_savings': self.token_savings,
            'category_distribution': dict(cat_counter),
            'workspace_distribution': dict(ws_counter),
            'auto_perceive': self._auto_perceive,
        }

    # ===== 自动感知 =====

    def set_auto_perceive(self, enabled: bool) -> Dict:
        """设置自动感知模式"""
        self._auto_perceive = enabled
        self._save()
        return {'status': 'ok', 'auto_perceive': enabled}

    # ===== 衰减 =====

    def _apply_decay(self):
        """体裁感知衰减 — dialogue 衰减比 definition 快"""
        now = time.time()
        decay_rates = {
            'dialogue': 0.95,
            'essay': 0.97,
            'data_summary': 0.98,
            'process': 0.99,
            'definition': 0.995,
            'paper': 0.995,
            'argument': 0.99,
            'knowledge': 0.98,
        }

        for node in self.nodes:
            if not isinstance(node, dict):
                continue
            days_since_access = (now - node.get('last_accessed', now)) / 86400
            if days_since_access < 1:
                continue
            genre = node.get('genre', 'knowledge')
            rate = decay_rates.get(genre, 0.98)
            for _ in range(int(days_since_access)):
                node['strength'] = node.get('strength', 100) * rate
            node['strength'] = max(node.get('strength', 100), 1)

    # ===== 上下文层 =====

    def _extract_source_context(self, text: str) -> str:
        """提取来源上下文"""
        stack = self.context_stack.stack
        if not stack:
            return ""

        window = 2
        if any(kw in text for kw in ['因为', '导致', '所以', '由于']):
            window = 5

        recent = stack[-window:]
        parts = []
        for ctx in recent:
            keywords = ctx.get('keywords', [])
            parts.extend(keywords[:3])

        return "、".join(list(dict.fromkeys(parts))[:10])

    def _write_context_layers(self, keyword: str, action: str, result: Dict):
        """写入三层上下文"""
        self._context_memory.save_session(keyword, {
            'entities': _extract_keywords(keyword),
            'injection': str(result.get('learned', ''))[:100],
        })
        self._context_memory.merge_topic(keyword, {
            'entities': _extract_keywords(keyword),
            'injection': keyword[:100],
        })

    # ===== 全局搜索 =====

    def global_search(self, keyword: str) -> Dict:
        """跨所有工作区搜索"""
        results = []
        kws = _extract_keywords(keyword)

        for i, node in enumerate(self.nodes):
            if not isinstance(node, dict) or not node.get("text"):
                continue
            text = node.get("text", "")
            if keyword in text or any(kw in text for kw in kws):
                results.append({
                    'index': i,
                    'text': text,
                    'category': node.get("category", ""),
                    'workspace': node.get("workspace", ""),
                })

        return {'status': 'ok', 'total': len(results), 'results': results[:20]}

    # ===== 备份/恢复 =====

    def backup(self) -> Dict:
        """备份知识数据"""
        backup_dir = self.data_dir / "data_backup"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.json"

        try:
            data = {
                'nodes': self.nodes,
                'stats': {
                    'learn_count': self.learn_count,
                    'query_count': self.query_count,
                    'search_count': self.search_count,
                    'token_savings': self.token_savings,
                },
                'version': VERSION,
                'backup_at': datetime.now().isoformat(),
            }
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

            # 清理旧备份（保留最近5个）
            backups = sorted(backup_dir.glob("backup_*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[5:]:
                old.unlink()

            return {'status': 'ok', 'file': str(backup_file)}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def restore(self, backup_file: str) -> Dict:
        """恢复知识数据"""
        try:
            with open(backup_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.nodes = data.get('nodes', [])
            stats = data.get('stats', {})
            self.learn_count = stats.get('learn_count', 0)
            self.query_count = stats.get('query_count', 0)
            self.search_count = stats.get('search_count', 0)
            self.token_savings = stats.get('token_savings', 0)
            self._rebuild_index()
            self._save()
            return {'status': 'ok', 'message': '数据已恢复'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}


# ============================================================
# _ContextStack — 上下文栈
# ============================================================

class _ContextStack:
    """上下文栈"""
    def __init__(self):
        self.stack = []

    def push(self, keywords, scene, weight=1.0):
        self.stack.append({
            'keywords': keywords,
            'scene': scene,
            'weight': weight,
            'timestamp': datetime.now().isoformat(),
        })
        if len(self.stack) > 20:
            self.stack = self.stack[-20:]

    def clear(self):
        self.stack = []

    def get_context(self):
        return self.stack[-5:] if self.stack else []


# ============================================================
# workbuddy_main — 统一入口
# ============================================================

_engine_instance = None

def get_engine() -> MemoryEngine:
    """获取引擎实例（单例）"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = MemoryEngine()
    return _engine_instance


def workbuddy_main(action: str, content: str = "", **kwargs) -> Dict:
    """Memory Skill 统一入口"""
    engine = get_engine()

    # 设置工作区
    try:
        project_path = os.environ.get("WORKBUDDY_PROJECT_DIR", os.getcwd())
        engine.set_workspace(project_path)
    except Exception:
        pass

    action_lower = action.lower().strip()

    # 命令路由
    if action_lower in ("session",):
        summary = engine.session()
        kwargs["_session_summary"] = summary
        return summary

    elif action_lower in ("inject",):
        result = engine.inject(content)
        return result

    elif action_lower in ("learn", "add", "记住", "help me remember"):
        idx = engine.add_node(content, **kwargs)
        if idx >= 0:
            node = engine.nodes[idx] if idx < len(engine.nodes) else None
            # 自动建边
            auto_edges = engine._auto_build_edges([idx])
            return {'status': 'ok', 'index': idx, 'text': content[:80],
                    'auto_edges': auto_edges, 'node': node}
        return {'status': 'error', 'message': '添加失败'}

    elif action_lower in ("extract", "learn_from_content"):
        return engine.learn_from_content(content)

    elif action_lower in ("search",):
        hops = kwargs.get('max_hops', kwargs.get('hops', 2))
        return engine.search(content, max_hops=int(hops))

    elif action_lower in ("find",):
        idx = engine.find_node(content)
        if idx is not None and isinstance(engine.nodes[idx], dict):
            return {'status': 'ok', 'index': idx, 'node': engine.nodes[idx]}
        return {'status': 'not_found'}

    elif action_lower in ("correct",):
        return engine.correct(content)

    elif action_lower in ("analyze",):
        result = DataAnalyzer.analyze(content)
        return {'status': 'ok', **result}

    elif action_lower in ("summarize", "总结"):
        result = Summarizer.summarize(content)
        return {'status': 'ok', **result}

    elif action_lower in ("seed",):
        return engine.seed(content)

    elif action_lower in ("modify", "修改"):
        if "|" in content:
            parts = content.split("|", 1)
            return engine.modify(parts[0].strip(), parts[1].strip())
        return {'status': 'error', 'message': '格式：旧文本|新文本'}

    elif action_lower in ("delete", "删除"):
        return engine.delete(content)

    elif action_lower in ("list", "记忆列表"):
        page = kwargs.get('page', 1)
        return engine.list_knowledge(int(page))

    elif action_lower in ("pending", "待确认"):
        return {'status': 'ok', 'message': '无待确认知识', 'items': []}

    elif action_lower in ("stats", "统计"):
        return engine.stats()

    elif action_lower in ("entangle", "纠缠"):
        return engine.entangle(content)

    elif action_lower in ("recommend", "推荐"):
        search_result = engine.search(content, max_hops=2)
        return {'status': 'ok', 'recommendations': search_result.get('details', [])}

    elif action_lower in ("trace", "追溯"):
        return engine.trace_source_context(content)

    elif action_lower in ("intent", "意图"):
        genre, tags, action_intent, content_intent, conf = GenreClassifier.classify_v2(content)
        return {'status': 'ok', 'genre': genre, 'tags': tags,
                'action_intent': action_intent, 'content_intent': content_intent,
                'confidence': conf}

    elif action_lower in ("context", "上下文"):
        ctx = engine.context_stack.get_context()
        return {'status': 'ok', 'context': ctx}

    elif action_lower in ("工作区", "workspace"):
        if content and content != "查看":
            engine.set_workspace(content)
        return engine.get_workspace_info()

    elif action_lower in ("全局搜索", "global_search"):
        return engine.global_search(content)

    elif action_lower in ("auto", "自动"):
        if "关" in content or "off" in content.lower():
            return engine.set_auto_perceive(False)
        return engine.set_auto_perceive(True)

    elif action_lower in ("备份", "backup"):
        return engine.backup()

    elif action_lower in ("恢复", "restore"):
        return engine.restore(content)

    elif action_lower in ("selfcheck", "自检"):
        return {'status': 'ok', 'message': '请使用 selfcheck.py 执行自检'}

    elif action_lower in ("architecture", "架构"):
        return {'status': 'ok', 'version': VERSION,
                'message': f'Memory Skill v{VERSION}，无鉴权版本'}

    elif action_lower in ("自动建边",):
        edges = sum(len(n.get("edges", [])) for n in engine.nodes
                    if isinstance(n, dict) and n.get("text"))
        return {'status': 'ok', 'auto_edges': edges,
                'message': f'自动建边原生内建，知识图谱共 {edges} 条边'}

    elif action_lower in ("dashboard", "仪表盘"):
        stats = engine.stats()
        return {'status': 'ok', 'stats': stats,
                'message': f'Token监测：已学习{stats["learn_count"]}次，'
                          f'查询{stats["query_count"]}次，'
                          f'节省约{stats["token_savings"]}tokens'}

    elif action_lower in ("suggest",):
        # 智能推荐
        recent = sorted([n for n in engine.nodes if isinstance(n, dict) and n.get("text")],
                       key=lambda n: n.get("last_accessed", 0), reverse=True)[:5]
        suggestions = [{'text': n.get("text", "")[:80], 'category': n.get("category", "")}
                       for n in recent]
        return {'status': 'ok', 'suggestions': suggestions}

    elif action_lower == "_set_workspace":
        return engine.set_workspace(content)

    elif action_lower == "_auto_edges_force":
        # Force auto-edges for recent nodes
        recent_indices = [i for i, n in enumerate(engine.nodes)
                         if isinstance(n, dict) and n.get("text")][-10:]
        count = engine._auto_build_edges(recent_indices)
        return {'auto_edges': count}

    # 默认：统一管线
    return engine.auto_process_v2(content)
