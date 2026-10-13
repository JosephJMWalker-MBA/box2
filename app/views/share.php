<section class="sharing" aria-label="Share BOX2">
    <a href="https://www.facebook.com/sharer/sharer.php?u=<?= e(rawurlencode($canonical)) ?>" target="_blank" rel="noopener">Share to Facebook</a>
    <a href="https://www.reddit.com/submit?url=<?= e(rawurlencode($canonical)) ?>&amp;title=<?= e(rawurlencode('BOX2 — Come Tell It Here First')) ?>" target="_blank" rel="noopener">Share to Reddit</a>
    <button type="button" class="secondary" data-share-url="<?= e($canonical) ?>">Share / copy link</button>
    <span data-share-status role="status"></span>
</section>
