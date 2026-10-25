"""How review text is turned into vectors and words for topic modelling (Phases 3 and 6).

The corpus is about 30% Bangla. The model used up to October 2026,
paraphrase-multilingual-MiniLM-L12-v2, was not trained on Bengali: it put every Bangla review
close together whatever it said, so BERTopic returned one 4,000-review "Bangla" topic and the
Bangla reviews carried no information about what travellers wanted. multilingual-e5 was trained
on Bengali, so a Bangla review about a waterfall lands near an English one about a waterfall.

Phase 4 still uses MiniLM for one narrow job, matching an English topic label to an English
preference, where it is calibrated and adequate.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sentence_transformers import SentenceTransformer

CLUSTER_MODEL_NAME = "intfloat/multilingual-e5-base"
# e5 models were trained with a role prefix; leaving it off lowers quality noticeably.
CLUSTER_TEXT_PREFIX = "passage: "
MAX_SEQ_LENGTH = 256  # reviews are short; longer inputs only slow the CPU run

# Python's \w does not match Bangla vowel signs (they are combining marks), so the default
# token pattern cuts every Bangla word into fragments and topic keywords come out as noise.
# Naming the Bengali block explicitly keeps words whole.
TOKEN_PATTERN = r"(?u)[\w\u0980-\u09FF]{2,}"

# Function words that would otherwise head every Bangla topic's keyword list.
BANGLA_STOP_WORDS = frozenset(
    "এই এটি এটা ওই সে তা আর ও এবং কিন্তু না নাই হয় হয়েছে হইছে করে করা করতে করেছি জন্য থেকে মধ্যে "
    "একটি একটা এক অনেক খুব আছে ছিল ছিলো হবে যায় যাই তাই যে কি কী এখানে সব আমি আমার আমরা আমাদের "
    "তবে পর পরে তার তাদের এর এদের যদি তো হলে হলো হল দিয়ে গিয়ে গিয়েছিলাম গিয়েছি সাথে সঙ্গে "
    "যেমন কোন কোনো বা মত মতো আরও আরো শুধু বেশ".split()
)
STOP_WORDS = sorted(set(ENGLISH_STOP_WORDS) | BANGLA_STOP_WORDS)


class PrefixedEncoder(SentenceTransformer):
    """A SentenceTransformer that adds the e5 role prefix to every text it embeds.

    BERTopic calls `encode` itself, so the prefix has to live in the model object.
    """

    def encode(self, sentences, *args, **kwargs):
        if isinstance(sentences, str):
            sentences = CLUSTER_TEXT_PREFIX + sentences
        else:
            sentences = [CLUSTER_TEXT_PREFIX + str(s) for s in sentences]
        return super().encode(sentences, *args, **kwargs)


def load_cluster_encoder() -> PrefixedEncoder:
    model = PrefixedEncoder(CLUSTER_MODEL_NAME, device="cpu")
    model.max_seq_length = MAX_SEQ_LENGTH
    return model
