<section class="page-heading"><p class="eyebrow">ARRIVE PREPARED</p><h1><?= in_array($route,['/arrive','/arrival'],true)?'Arrive prepared.':'Read the room.' ?></h1>
<p>Bring your joke, respect the room, leave your best set on stage, then build the next one.</p></section>
<?php if (in_array($route,['/arrive','/arrival'],true)): ?>
<section class="panel"><h2>Arrival walkthrough</h2>
<p>Arrive T−20 through T−10: 10–20 minutes before your stage time, never earlier. Check in immediately upon arrival and be on deck at T−10. Arriving at T−10 means being ready at once.</p>
<?php if (config()['venue_public_enabled']): ?>
<p><strong><?= e(config()['venue_address']) ?></strong></p><p><?= nl2br(e(config()['arrival_text'])) ?></p>
<?php $video=query("SELECT * FROM media_assets WHERE kind='arrival' AND approved=1 ORDER BY created_at DESC LIMIT 1")->fetch(); ?>
<?php if ($video): ?><video controls preload="metadata" aria-label="Parking and entry walkthrough" src="<?= e(url('/media/'.$video['id'])) ?>"></video>
<h3>Text walkthrough</h3><p><?= nl2br(e($video['transcript'])) ?></p>
<?php else: ?><p>A host-reviewed parking and entry video has not been published. Use the approved written instructions.</p><?php endif; ?>
<?php else: ?><p>Venue access and parking instructions are not published until premises and routes are verified. Public walk-in access is not open.</p><?php endif; ?>
</section>
<?php endif; ?>
<section class="rules-stack"><?php require __DIR__.'/rules-content.php'; ?></section>
<a class="button" href="<?= e(url('/book')) ?>">Back to booking</a>
