export type Source = {
  label: string;
  source_type: string | null;
  article_number: number | null;
  bab: string;
  fasl: string;
  text: string;
  cited: boolean;
};

export type AskResponse = {
  answer: string;
  sources: Source[];
  article_number: number | null;
  has_unverified_citation: boolean;
};
