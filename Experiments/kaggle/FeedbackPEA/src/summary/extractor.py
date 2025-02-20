from typing import List
import numpy as np
import math
import torch
import random


from utils import evaluate_rouge

from sentence_transformers import SentenceTransformer, util
import torch


class PacSumExtractor:
    def __init__(
        self,
        model_name_or_path: str,
        extract_num: int = 3,
        beta: float = 3,
        lambda1: float = -0.2,
        lambda2: float = -0.2,
    ):

        self.model = model = SentenceTransformer(model_name_or_path)

        self.extract_num = extract_num
        self.beta = beta
        self.lambda1 = lambda1
        self.lambda2 = lambda2

    def extract_summary(self, data_iterator):

        summaries = []
        references = []

        for item in data_iterator:
            article, abstract, inputs = item
            if len(article) <= self.extract_num:
                summaries.append(article)
                references.append([abstract])
                continue

            edge_scores = self._calculate_similarity_matrix(*inputs)
            ids = self._select_tops(
                edge_scores, beta=self.beta, lambda1=self.lambda1, lambda2=self.lambda2
            )
            summary = list(map(lambda x: article[x], ids))
            summaries.append(summary)
            references.append([abstract])

        result = evaluate_rouge(summaries, references, remove_temp=True, rouge_args=[])

    def tune_hparams(self, data_iterator, example_num=1000):

        summaries, references = [], []
        k = 0
        hparam_list = []
        for item in data_iterator:
            article, abstract, inputs = item
            edge_scores = self._calculate_similarity_matrix(*inputs)
            tops_list, hparam_list = self._tune_extractor(edge_scores)

            summary_list = [list(map(lambda x: article[x], ids)) for ids in tops_list]
            summaries.append(summary_list)
            references.append([abstract])
            k += 1
            print(k)
            if k % example_num == 0:
                break

        best_rouge = 0
        best_hparam = []
        for i in range(len(summaries[0])):
            print("threshold :  " + str(hparam_list[i]) + "\n")
            # print("non-lead ratio : "+str(ratios[i])+'\n')
            result = evaluate_rouge(
                [summaries[k][i] for k in range(len(summaries))],
                references,
                remove_temp=True,
                rouge_args=[],
            )

            if result["rouge_1_f_score"] > best_rouge:
                best_rouge = result["rouge_1_f_score"]
                best_hparam = hparam_list[i]

        print(
            "The best hyper-parameter :  beta %.4f , lambda1 %.4f, lambda2 %.4f "
            % (best_hparam[0], best_hparam[1], best_hparam[2])
        )
        print("The best rouge_1_f_score :  %.4f " % best_rouge)

        self.beta = best_hparam[0]
        self.lambda1 = best_hparam[1]
        self.lambda2 = best_hparam[2]

    def _select_tops(self, edge_scores, beta, lambda1, lambda2):

        min_score = edge_scores.min()
        max_score = edge_scores.max()
        edge_threshold = min_score + beta * (max_score - min_score)
        new_edge_scores = edge_scores - edge_threshold
        forward_scores, backward_scores, _ = self._compute_scores(new_edge_scores, 0)
        forward_scores = 0 - forward_scores

        paired_scores = []
        for node in range(len(forward_scores)):
            paired_scores.append(
                [node, lambda1 * forward_scores[node] + lambda2 * backward_scores[node]]
            )

        # shuffle to avoid any possible bias
        random.shuffle(paired_scores)
        paired_scores.sort(key=lambda x: x[1], reverse=True)
        extracted = [item[0] for item in paired_scores[: self.extract_num]]

        return extracted

    def _compute_scores(self, similarity_matrix, edge_threshold):

        forward_scores = [0 for i in range(len(similarity_matrix))]
        backward_scores = [0 for i in range(len(similarity_matrix))]
        edges = []
        for i in range(len(similarity_matrix)):
            for j in range(i + 1, len(similarity_matrix[i])):
                edge_score = similarity_matrix[i][j]
                if edge_score > edge_threshold:
                    forward_scores[j] += edge_score
                    backward_scores[i] += edge_score
                    edges.append((i, j, edge_score))

        return np.asarray(forward_scores), np.asarray(backward_scores), edges

    def _tune_extractor(self, edge_scores):

        tops_list = []
        hparam_list = []
        num = 10
        for k in range(num + 1):
            beta = k / num
            for i in range(11):
                lambda1 = i / 10
                lambda2 = 1 - lambda1
                extracted = self._select_tops(
                    edge_scores, beta=beta, lambda1=lambda1, lambda2=lambda2
                )

                tops_list.append(extracted)
                hparam_list.append((beta, lambda1, lambda2))

        return tops_list, hparam_list

    def _calculate_similarity_matrix(self, document: List[str]) -> torch.Tensor:
        embeddings: torch.Tensor = self.model.encode(document)  # type: ignore
        return util.dot_score(embeddings, embeddings)

    # def _calculate_similarity_matrix(self, x, t, w, x_c, t_c, w_c, pair_indice):
    #     # doc: a list of sequences, each sequence is a list of words

    #     def pairdown(scores, pair_indice, length):
    #         # 1 for self score
    #         out_matrix = np.ones((length, length))
    #         for pair in pair_indice:
    #             out_matrix[pair[0][0]][pair[0][1]] = scores[pair[1]]
    #             out_matrix[pair[0][1]][pair[0][0]] = scores[pair[1]]

    #         return out_matrix

    #     scores = self._generate_score(x, t, w, x_c, t_c, w_c)
    #     doc_len = int(math.sqrt(len(x) * 2)) + 1
    #     similarity_matrix = pairdown(scores, pair_indice, doc_len)

    #     return similarity_matrix

    # def _generate_score(self, x, t, w, x_c, t_c, w_c):

    #     # score =  log PMI -log k
    #     scores = torch.zeros(len(x)).cuda()
    #     step = 20
    #     for i in range(0, len(x), step):

    #         batch_x = x[i : i + step]
    #         batch_t = t[i : i + step]
    #         batch_w = w[i : i + step]
    #         batch_x_c = x_c[i : i + step]
    #         batch_t_c = t_c[i : i + step]
    #         batch_w_c = w_c[i : i + step]

    #         inputs = tuple(
    #             t.to("cuda")
    #             for t in (batch_x, batch_t, batch_w, batch_x_c, batch_t_c, batch_w_c)
    #         )
    #         batch_scores, batch_pros = self.model(*inputs)
    #         scores[i : i + step] = batch_scores.detach()

    #     return scores

    # def _load_edge_model(self, bert_model_file, bert_config_file):

    #     bert_config = BertConfig.from_json_file(bert_config_file)
    #     model = BertEdgeScorer(bert_config)
    #     model_states = torch.load(bert_model_file)
    #     print(model_states.keys())
    #     model.bert.load_state_dict(model_states)

    #     model.cuda()
    #     model.eval()
    #     return model
