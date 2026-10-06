export type Post = { id: number; author_id: string | null; handle: string; campus: string; flair: string; title: string; body: string; kind: string; media_url: string | null; votes: number; comments: number; created_at: string };
export const campuses = ['UNILAG', 'UI', 'OAU', 'UNN', 'ABU'];
export const mediaKinds = new Set(['square','four-three','landscape','wide','portrait','tall','grid2','grid3','grid4','carousel','video','vertical-video']);
export const videoKinds = new Set(['video','vertical-video']);
export type SearchParts = { words: string[]; phrases: string[]; excluded: string[]; from: string; minVotes: number; media: boolean };
export function parseSearch(input: string): SearchParts {
  const out: SearchParts = { words: [], phrases: [], excluded: [], from: '', minVotes: 0, media: false };
  for (const token of input.match(/"[^"]+"|\S+/g) ?? []) {
    const term = token.toLowerCase();
    if (term.startsWith('"') && term.endsWith('"')) out.phrases.push(term.slice(1, -1));
    else if (term.startsWith('from:')) out.from = term.slice(5).replace(/^@/, '');
    else if (term.startsWith('min_votes:')) out.minVotes = Math.max(0, Number(term.slice(10)) || 0);
    else if (term.startsWith('filter:')) out.media = /^(media|images|videos)$/.test(term.slice(7));
    else if (term.startsWith('-') && term.length > 1) out.excluded.push(term.slice(1));
    else out.words.push(term.replace(/^#/, ''));
  }
  return out;
}
export function searchPosts(posts: Post[], input: string, filters: { school: boolean; verified: boolean; recent: boolean }, campus: string) {
  const p = parseSearch(input);
  return posts.filter(post => {
    const text = `${post.title} ${post.body} ${post.campus} ${post.flair} ${post.handle}`.toLowerCase();
    return p.words.every(w => text.includes(w)) && p.phrases.every(w => text.includes(w)) && !p.excluded.some(w => text.includes(w))
      && (!p.from || post.handle.toLowerCase() === p.from) && post.votes >= p.minVotes && (!p.media || mediaKinds.has(post.kind))
      && (!filters.school || post.campus === campus) 
      && (!filters.recent || Date.now() - new Date(post.created_at).getTime() <= 86400000);
  });
}
export function formatCount(n: number) { return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n); }
