<section class="page-heading"><p class="eyebrow">FOR JOKE + TAG WRITERS</p><h1>Bring the line.</h1><p>Your writing stays yours. Submissions are private to authorized hosts. Selection and performance are not guaranteed.</p></section>
<?php if ($route==='/withdraw'): ?>
<?php if (!$notice): ?><form method="post" class="panel"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><input type="hidden" name="token" value="<?= e($_GET['token']??'') ?>"><p>Withdraw permission prospectively before production starts. This does not recall previously published copies.</p><button class="button">Withdraw future permission</button></form><?php endif; ?>
<?php elseif ($result): ?><section class="panel"><h2>Received privately.</h2><p>Submission code: <?= e($result['id']) ?></p><p>Keep this private link: <a href="<?= e($result['withdrawal']) ?>">Withdraw future permission</a>. No email receipt is sent for writer submissions in this MVP.</p></section>
<?php else: ?><form method="post" class="panel" action="<?= e(url('/writers')) ?>"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>">
<div class="honeypot" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
<fieldset <?= !forms_ready()?'disabled':'' ?>><legend>Private submission</legend><div class="field-grid">
<label>Alias<input name="alias" maxlength="100" required></label><label>Contact email (optional)<input name="contact" type="email" maxlength="254"></label>
<label>Preferred credit<input name="credit" maxlength="100"></label></div>
<label>Your original joke, punchline, or tag<textarea name="text" rows="8" maxlength="10000" required></textarea></label>
<fieldset class="permissions"><legend>Express permission by medium — defaults off</legend>
<label class="check"><input type="checkbox" name="perform_allowed" value="1">Host may perform this writing.</label>
<label class="check"><input type="checkbox" name="publish_allowed" value="1">Public/video release is allowed.</label>
<label class="check"><input type="checkbox" name="ai_allowed" value="1">AI trailer or visual adaptation is allowed.</label>
<label class="check"><input type="checkbox" name="music_allowed" value="1">Music / Suno adaptation is allowed.</label></fieldset>
<label class="check"><input type="checkbox" name="terms_agreed" value="1" required>I own or have rights to submit this writing and accept the <a href="<?= e(url('/terms')) ?>">terms</a>. This grants only my checked permissions, not ownership.</label>
<button class="button">Submit privately</button></fieldset>
<?php if (!forms_ready()): ?><p>Secure submissions require completed setup and HTTPS, or explicit loopback local mode.</p><?php endif; ?>
</form><?php endif; ?>
