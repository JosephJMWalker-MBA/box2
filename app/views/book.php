<?php
if ($route==='/respond' && !$result && !$error) {
    $token=authorized_token($_GET);
    $preview=booking_record($token['booking_id']);
    echo '<section class="panel"><h1>Your booking</h1><p>'.e(local_label($preview['start_at_utc'])).'</p>';
    echo '<form method="post"><input type="hidden" name="csrf" value="'.e(csrf()).'">';
    foreach (['action','token','signature'] as $key) echo '<input type="hidden" name="'.e($key).'" value="'.e($_GET[$key]).'">';
    echo '<button class="button">'.e(ucfirst($_GET['action'])).' this booking</button></form></section>';return;
}
if ($result && isset($result['booking'])) {
    $booking=$result['booking'];
?>
<section class="panel receipt"><p class="eyebrow">BOOKING <?= e($booking['status']) ?></p><h1>Your place in the room.</h1>
<dl><dt>Booking code</dt><dd><?= e($booking['id']) ?></dd><dt>Show evening</dt><dd><?= e($booking['show_date']) ?></dd>
<dt>Actual stage date/time</dt><dd><?= e(local_label($booking['start_at_utc'])) ?></dd><dt>Set length</dt><dd>5 minutes within a 10-minute allocation</dd>
<dt>Check in</dt><dd><?= e(local_label(utc((new DateTimeImmutable($booking['start_at_utc']))->modify('-20 minutes')))) ?></dd></dl>
<p><?= e(config()['venue_public_enabled']?config()['venue_address']:'Venue information not yet approved for publication.') ?></p>
<p><?= e(config()['arrival_text']) ?></p><p><a href="<?= e(url('/rules')) ?>">Review orientation</a> · <a href="https://www.twitch.tv/cantonrefinery">Watch on Twitch</a></p>
<p><?= config()['mail_transport']==='disabled'?'Email confirmations and reminders are unavailable. Keep this booking code and the links below.':'Email is queued; provider acceptance and delivery are not yet verified. Keep the links below.' ?></p>
<?php if (isset($result['links'])): ?><p><a href="<?= e($result['links']['confirm']) ?>">Confirm</a> · <a href="<?= e($result['links']['cancel']) ?>">Cancel</a></p><?php endif; ?>
</section>
<?php return; } if ($route==='/respond') return;
$nights=query('SELECT * FROM show_nights WHERE end_at_utc>? ORDER BY show_date LIMIT 28',[utc()])->fetchAll();
$sharedId=isset($_GET['show'])&&is_string($_GET['show'])?query('SELECT id FROM show_nights WHERE show_date=?',[$_GET['show']])->fetchColumn():false;
$nightId=filter_var($_POST['night_id']??$_GET['night']??($sharedId?:($nights[0]['id']??null)),FILTER_VALIDATE_INT);
$night=$nightId?query('SELECT * FROM show_nights WHERE id=?',[$nightId])->fetch():false;
$slots=$night?availability((int)$night['id']):[];
?>
<section class="page-heading"><p class="eyebrow">FIVE MINUTES. ORIGINAL COMEDY.</p><h1>Book your reps.</h1><p>Times are America/New_York; an after-midnight slot belongs to the previous evening's show.</p></section>
<?php if (!bookings_open()): ?><p class="message">Reservations are not open yet. This schedule preview does not grant walk-in access.</p><?php endif; ?>
<form method="get" class="night-picker"><label for="night">Show evening</label><select name="night" id="night">
<?php foreach ($nights as $item): ?><option value="<?= (int)$item['id'] ?>" <?= $nightId===$item['id']?'selected':'' ?>><?= e($item['show_date'].' · '.$item['status'].($item['override_note']?' · '.$item['override_note']:'')) ?></option><?php endforeach; ?>
</select><button class="secondary">See blocks</button></form>
<?php if ($night): ?><p><?= e($night['override_note']) ?><?= $night['guest_host']?' · Guest host: '.e($night['guest_host']):'' ?></p><?php endif; ?>
<form method="post" action="<?= e(url('/book')) ?>" class="panel booking-form" id="booking-form">
<input type="hidden" name="csrf" value="<?= e(csrf()) ?>"><input type="hidden" name="night_id" value="<?= (int)$nightId ?>">
<div class="honeypot" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
<section data-orientation><p class="eyebrow">BEFORE YOU BOOK</p><h2>Get to know BOX2.</h2><p data-orientation-progress role="status"></p>
<div data-orientation-cards><?php require __DIR__.'/rules-content.php'; ?></div>
<label class="check"><input type="checkbox" name="orientation_agreed" value="1" required data-orientation-check>I have read and acknowledge every part of performer orientation.</label>
<div class="orientation-actions" hidden data-orientation-actions><button type="button" class="secondary" data-orientation-back>Previous</button><button type="button" class="button" data-orientation-next>I understand</button></div>
</section>
<div data-booking-fields>
<fieldset <?= !bookings_open()?'disabled':'' ?>>
<legend>Choose a stage block</legend><div class="slot-grid">
<?php foreach ($slots as $slot): ?><label class="slot <?= e($slot['state']) ?>">
<input type="radio" name="slot_id" value="<?= (int)$slot['id'] ?>" required <?= $slot['state']!=='available'?'disabled':'' ?>>
<span><?= e(local_label($slot['start_at_utc'])) ?><small><?= e($slot['visibility']==='private'?'Private · no recording':($slot['state']==='available'?'Livestream eligible':$slot['state'])) ?></small></span></label><?php endforeach; ?>
</div><?php if (!$slots): ?><p>No scheduled blocks are published for this show.</p><?php endif; ?>
<div class="field-grid"><label>Stage name<input name="stage_name" maxlength="100" autocomplete="nickname" required></label>
<label>Legal/full name (optional)<input name="full_name" maxlength="120" autocomplete="name"></label>
<label>Email<input type="email" name="email" maxlength="254" autocomplete="email" required></label>
<label>Phone (optional)<input type="tel" name="phone" maxlength="40" autocomplete="tel"></label>
<label>Social handle (optional)<input name="social_handle" maxlength="100"></label>
<label>Comedy format<select name="performance_type" required><option value="">Choose format</option><?php foreach(BOX2_FORMATS as $key=>$label): ?><option value="<?= e($key) ?>"><?= e($label) ?></option><?php endforeach; ?></select></label></div>
<fieldset class="permissions"><legend>Separate recording choices — all start off</legend>
<label class="check"><input type="checkbox" name="livestream_allowed" value="1">I permit livestream broadcast. Required for public blocks.</label>
<label class="check"><input type="checkbox" name="archive_allowed" value="1">I permit BOX2 archival recording for <?= (int)config()['vod_retention_days'] ?> days.</label>
<label class="check"><input type="checkbox" name="clips_allowed" value="1">I permit approved short host clips. Requires archive permission.</label>
<label class="check"><input type="checkbox" name="adaptation_allowed" value="1">I permit creative adaptation of the accepted performance within the terms.</label>
<label class="check"><input type="checkbox" name="feedback_allowed" value="1">I welcome optional, host-moderated feedback.</label>
<p>Leave broadcast and recording off for a labelled private rehearsal. The host must stop OBS/Twitch and all recording. Live-only sets require VOD/recording disabled by the host. Viewers may retain their own copies.</p></fieldset>
<label>Teleprompter notes (private to authorized hosts)<textarea name="teleprompter_text" maxlength="5000" rows="5"></textarea></label>
<label class="check"><input type="checkbox" name="terms_agreed" value="1" required>I accept the <a href="<?= e(url('/terms')) ?>" target="_blank" rel="noopener">terms and selected recording permissions</a> and understand the <a href="<?= e(url('/privacy')) ?>">privacy policy</a>. I retain ownership of my material.</label>
<button class="button">Reserve stage block</button>
</fieldset></div></form>
<?php require __DIR__.'/share.php'; ?>
