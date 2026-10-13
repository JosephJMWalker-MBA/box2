<?php
if ($route==='/respond' && !$result && !$error) {
    $token=authorized_token($_GET);
    $booking=booking_record($token['booking_id']);
    echo '<section class="panel"><h1>Your booking</h1>';
    require __DIR__.'/booking-summary.php';
    echo '<form method="post"><input type="hidden" name="csrf" value="'.e(csrf()).'">';
    foreach (['action','token','signature'] as $key) echo '<input type="hidden" name="'.e($key).'" value="'.e($_GET[$key]).'">';
    echo '<button class="button">'.e(ucfirst($_GET['action'])).' this booking</button></form></section>';return;
}
if ($result && isset($result['booking'])) {
    $booking=$result['booking'];
?>
<section class="panel receipt"><p class="eyebrow">BOOKING <?= e($booking['status']) ?></p><h1>Your place in the room.</h1>
<?php require __DIR__.'/booking-summary.php'; ?>
<p><?= e(config()['venue_public_enabled']?config()['venue_address']:'Venue information not yet approved for publication.') ?></p>
<?php if (config()['venue_public_enabled']): ?><p><?= e(config()['arrival_text']) ?></p><p><a href="<?= e(url('/arrival')) ?>">Approved arrival updates</a></p><?php endif; ?>
<p><a href="<?= e(url('/rules')) ?>">Review orientation</a> · <a href="https://www.twitch.tv/cantonrefinery">Watch on Twitch</a></p>
<p><?= config()['mail_transport']==='disabled'?'Email confirmations and reminders are unavailable. Keep this booking code and the links below.':'Email is queued; provider acceptance and delivery are not yet verified. Keep the links below.' ?></p>
<?php if (isset($result['links'])): ?><p><a href="<?= e($result['links']['confirm']) ?>">Confirm</a> · <a href="<?= e($result['links']['cancel']) ?>">Cancel</a></p><?php endif; ?>
</section>
<?php return; } if ($route==='/respond') return;
$nights=query('SELECT * FROM show_nights WHERE end_at_utc>? ORDER BY show_date LIMIT 28',[utc()])->fetchAll();
$sharedId=isset($_GET['show'])&&is_string($_GET['show'])?query('SELECT id FROM show_nights WHERE show_date=?',[$_GET['show']])->fetchColumn():false;
$nightId=filter_var($_POST['night_id']??$_GET['night']??($sharedId?:($nights[0]['id']??null)),FILTER_VALIDATE_INT);
$night=$nightId?query('SELECT * FROM show_nights WHERE id=?',[$nightId])->fetch():false;
$slots=$night?availability((int)$night['id']):[];
$posted=is_string($_POST['csrf']??null)&&hash_equals(csrf(),$_POST['csrf'])?$_POST:[];
$durations=[];
foreach ($slots as $slot) $durations=array_merge($durations,$slot['durations']);
$durations=array_values(array_unique($durations));sort($durations);
$duration=filter_var($posted['duration_minutes']??5,FILTER_VALIDATE_INT);
if (!in_array($duration,$durations,true)) $duration=$durations[0]??5;
$acknowledged=flag($posted,'orientation_agreed') && ($posted['orientation_version']??'')===BOX2_TERMS;
$value=fn(string $name): string => e(is_string($posted[$name]??null)?$posted[$name]:'');
?>
<section class="page-heading"><p class="eyebrow">ORIGINAL COMEDY. ROOM TO WORK.</p><h1>Book your reps.</h1><p>5 / 10 / 15 stage minutes reserve 10 / 20 / 30 calendar minutes. Times are America/New_York; after-midnight sets belong to the previous evening's show.</p></section>
<?php if (!bookings_open()): ?><p class="message">Reservations are not open yet. This schedule preview does not grant walk-in access.</p><?php endif; ?>
<form method="get" id="night-picker-form" action="<?= e(url('/book')) ?>" data-slots-url="<?= e(url('/api/slots')) ?>"></form>
<form method="post" action="<?= e(url('/book')) ?>" class="panel booking-form" id="booking-form">
<input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><input type="hidden" name="night_id" value="<?= (int)$nightId ?>">
<input type="hidden" name="orientation_version" value="<?= e(BOX2_TERMS) ?>">
<div class="honeypot" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
<section data-orientation data-complete="<?= $acknowledged?'1':'0' ?>"><p class="eyebrow">BEFORE YOU BOOK</p><h2>Read the room before you book.</h2><p data-orientation-progress role="status"></p>
<progress class="onboarding-meter" data-orientation-meter max="9" value="<?= $acknowledged?'9':'0' ?>" aria-label="Acknowledged orientation cards"></progress>
<div data-orientation-cards><?php require __DIR__.'/rules-content.php'; ?></div>
<label class="check"><input type="checkbox" name="orientation_agreed" value="1" required data-orientation-check <?= $acknowledged?'checked':'' ?>>I have read and acknowledge all nine current orientation cards.</label>
<div class="orientation-actions" hidden data-orientation-actions><button type="button" class="secondary" data-orientation-back>Previous</button><button type="button" class="button" data-orientation-next>I understand</button></div>
</section>
<div data-booking-fields>
<p class="booking-progress" data-booking-progress role="status" hidden></p>
<section data-booking-step="1"><p class="eyebrow">STEP 01</p><h2>Pick your night + set length</h2>
<div class="night-picker"><label for="night">Show evening</label><select name="night" id="night" form="night-picker-form">
<?php foreach ($nights as $item): ?><option value="<?= (int)$item['id'] ?>" <?= $nightId===$item['id']?'selected':'' ?>><?= e($item['show_date'].' · '.$item['status'].($item['override_note']?' · '.$item['override_note']:'')) ?></option><?php endforeach; ?>
</select><button class="secondary" form="night-picker-form">See blocks</button></div>
<p id="slot-status" role="status"><?= $night?e($night['override_note'].($night['guest_host']?' · Guest host: '.$night['guest_host']:'')):'' ?></p>
<fieldset <?= !bookings_open()?'disabled':'' ?>>
<legend>Set length</legend><label for="set-length">Stage minutes</label><select name="duration_minutes" id="set-length" required>
<?php foreach ($durations as $minutes): ?><option value="<?= $minutes ?>" <?= $minutes===$duration?'selected':'' ?>><?= $minutes ?> min set · <?= $minutes*2 ?> min reserved</option><?php endforeach; ?>
</select><p class="fine-print">Each five minutes of stage time reserves one ten-minute allocation for host/reset buffer. All allocations must be consecutive, open, and in the same recording mode.</p>
<div class="slot-grid" id="slot-grid">
<?php foreach ($slots as $slot): ?><label class="slot <?= e($slot['state']) ?>" data-durations="<?= e(implode(',',$slot['durations'])) ?>" data-visibility="<?= e($slot['visibility']) ?>">
<input type="radio" name="slot_id" value="<?= (int)$slot['id'] ?>" required <?= !in_array($duration,$slot['durations'],true)?'disabled':'' ?> <?= ($posted['slot_id']??'')===(string)$slot['id']&&in_array($duration,$slot['durations'],true)?'checked':'' ?>>
<span><?= e($slot['label']) ?><small><?= e($slot['state']!=='available'?$slot['state']:($slot['visibility']==='private'?'Private · no recording':'Public · livestream permission required')) ?></small></span></label><?php endforeach; ?>
</div><?php if (!$durations): ?><p>No consecutive open allocations fit a set on this show.</p><?php endif; ?>
<button type="button" class="button" data-booking-next hidden>Continue with this block</button></fieldset></section>
<section data-booking-step="2"><p class="eyebrow">STEP 02</p><h2>Who's going up?</h2>
<fieldset <?= !bookings_open()?'disabled':'' ?>><legend>Performer details</legend>
<div class="field-grid"><label>Stage name<input name="stage_name" maxlength="100" autocomplete="nickname" value="<?= $value('stage_name') ?>" required></label>
<label>Legal/full name (optional)<input name="full_name" maxlength="120" autocomplete="name" value="<?= $value('full_name') ?>"></label>
<label>Email<input type="email" name="email" maxlength="254" autocomplete="email" value="<?= $value('email') ?>" required></label>
<label>Phone (optional)<input type="tel" name="phone" maxlength="40" autocomplete="tel" value="<?= $value('phone') ?>"></label>
<label>Social handle (optional)<input name="social_handle" maxlength="100" value="<?= $value('social_handle') ?>"></label>
<label>Comedy format<select name="performance_type" required><option value="">Choose format</option><?php foreach(BOX2_FORMATS as $key=>$label): ?><option value="<?= e($key) ?>" <?= ($posted['performance_type']??'')===$key?'selected':'' ?>><?= e($label) ?></option><?php endforeach; ?></select></label></div>
<div class="booking-actions"><button type="button" class="secondary" data-booking-back hidden>Change block</button><button type="button" class="button" data-booking-next hidden>Recording choices</button></div></fieldset></section>
<section data-booking-step="3"><p class="eyebrow">STEP 03</p><h2>Your permissions + notes</h2>
<fieldset <?= !bookings_open()?'disabled':'' ?>><legend>Recording and release</legend>
<fieldset class="permissions"><legend>Separate recording choices — all start off</legend>
<label class="check"><input type="checkbox" name="livestream_allowed" value="1" <?= flag($posted,'livestream_allowed')?'checked':'' ?>>I permit livestream broadcast. Required for public blocks.</label>
<label class="check"><input type="checkbox" name="archive_allowed" value="1" <?= flag($posted,'archive_allowed')?'checked':'' ?>>I permit BOX2 archival recording for <?= (int)config()['vod_retention_days'] ?> days.</label>
<label class="check"><input type="checkbox" name="clips_allowed" value="1" <?= flag($posted,'clips_allowed')?'checked':'' ?>>I permit approved short host clips. Requires archive permission.</label>
<label class="check"><input type="checkbox" name="adaptation_allowed" value="1" <?= flag($posted,'adaptation_allowed')?'checked':'' ?>>I permit creative adaptation of the accepted performance within the terms.</label>
<label class="check"><input type="checkbox" name="feedback_allowed" value="1" <?= flag($posted,'feedback_allowed')?'checked':'' ?>>I welcome optional, host-moderated feedback.</label>
<p>Leave broadcast and recording off for a labelled private rehearsal. The host must stop OBS/Twitch and all recording. Live-only sets require VOD/recording disabled by the host. Viewers may retain their own copies.</p></fieldset>
<label>Teleprompter notes (private to authorized hosts)<textarea name="teleprompter_text" maxlength="5000" rows="5"><?= $value('teleprompter_text') ?></textarea></label>
<label class="check"><input type="checkbox" name="terms_agreed" value="1" required <?= flag($posted,'terms_agreed')&&$acknowledged?'checked':'' ?>>I accept the <a href="<?= e(url('/terms')) ?>" target="_blank" rel="noopener">terms and selected recording permissions</a> and understand the <a href="<?= e(url('/privacy')) ?>">privacy policy</a>. I retain ownership of my material.</label>
<button type="button" class="secondary" data-booking-back hidden>Your details</button>
<button class="button">Reserve stage block</button>
</fieldset></section></div></form>
<?php require __DIR__.'/share.php'; ?>
