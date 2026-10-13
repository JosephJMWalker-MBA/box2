<section class="hero">
    <div><p class="eyebrow">EVERYBODY STARTS SOMEWHERE. START HERE.</p>
        <h1>Come tell it<br>here first.</h1>
        <p class="lede">A Canton, Ohio comedy rehearsal workshop and hosted studio program.<br>Bring your joke. Everything else is here.</p>
        <a class="button" href="<?= e(url('/book')) ?>">Find a stage block</a>
    </div><aside class="poster"><span>BOOK</span><span>SHOW UP</span><span>WORK IT</span><span>COME BACK</span></aside>
</section>
<section class="stream panel">
    <p class="eyebrow">THE ONLINE ROOM · CANTONREFINERY</p><h2>Watch the stage</h2>
    <p>During declared studio windows, programming may include host talks, original sketches, house interludes and consenting performances. Stream availability is determined by Twitch; an interlude does not identify anyone in the room.</p>
    <?php $host=parse_url(config()['base_url'],PHP_URL_HOST); ?>
    <?php if (secure_request() && in_array($host,config()['twitch_parents'],true)): ?>
        <div class="twitch-wide"><iframe title="BOX2 on Twitch" loading="lazy" allowfullscreen
            src="https://player.twitch.tv/?channel=<?= e(config()['twitch_channel']) ?>&amp;parent=<?= e($host) ?>&amp;autoplay=false"></iframe></div>
        <p class="narrow-only">Use the Twitch link below on smaller screens.</p>
    <?php else: ?><div class="stream-fallback">The embedded player is unavailable. Watch on Twitch below.</div><?php endif; ?>
    <a class="text-link" href="https://www.twitch.tv/<?= e(config()['twitch_channel']) ?>" rel="noopener" target="_blank">Watch on Twitch</a>
</section>
<section class="three-up">
    <article class="panel"><p class="eyebrow">ROOM FOR REPS</p><h2>Original comedy.</h2><p>First attempt or touring set, you get focus. Choose 5, 10, or 15 stage minutes when adjacent allocations fit. Stand-up, sketches/characters, host practice, and portable-instrument musical comedy.</p></article>
    <article class="panel"><p class="eyebrow">SOBER + RESPECTFUL</p><h2>A room for reps.</h2><p>No competition, public ranking, or pressure to socialize. Respect the clock, volunteers, neighbors, and the performer on stage.</p></article>
    <article class="panel dark"><p class="eyebrow">YOUR MATERIAL STAYS YOURS</p><h2>Your set. Your choices.</h2><p>Choose room broadcast, archive, clips, adaptation, and feedback separately. An unrecorded rehearsal must have every room source and recorder off; an independently verified house-only program may continue without exposing the room.</p></article>
</section>
<section class="panel"><p class="eyebrow">THE SCHEDULE</p><h2>Six nights. A little room to grow.</h2>
    <p>Sun / Mon / Wed / Thu / Fri / Sat · 9 PM–2 AM · America/New_York. Tuesday is reserved for outside performances. Date-specific exceptions appear in the schedule.</p>
    <p><?= bookings_open()?'Stage blocks are available to reserve.':'Reservations are not open yet. The schedule is a preview, not an invitation to walk in.' ?></p>
    <p>Crush a set and you may be considered for a future Laundry Set: long enough to wash and dry a load. Selection and clips are never guaranteed.</p>
    <a class="button" href="<?= e(url('/book')) ?>">See actual availability</a>
</section>
<section class="panel"><p class="eyebrow">ONE OPTIONAL WEEKLY SHORT</p><h2>Top 5 Jokes This Week.</h2><p>With specific permission, up to five authorized joke moments may be considered for one manually edited vertical compilation, organically shared to TikTok, Instagram Reels, Facebook Reels and YouTube Shorts. Fewer or none is fine. This is not a ranking of comedians, guaranteed inclusion, paid promotion or a promise of views.</p><p>Bored yet? Book a slot and take over the stage at your scheduled time. This is a booking invitation, not immediate access or a guaranteed live appearance.</p></section>
<?php require __DIR__.'/share.php'; ?>
