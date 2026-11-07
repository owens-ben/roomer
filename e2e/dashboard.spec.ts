import { test, expect } from '@playwright/test';

test.describe('Dashboard loads', () => {
  test('page loads with correct title', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('Roomer');
  });

  test('header renders with logo and status bar', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h1')).toHaveText('Roomer');
    await expect(page.locator('.subtitle')).toBeVisible();
    await expect(page.locator('#ha-status')).toBeVisible();
    await expect(page.locator('#ollama-status')).toBeVisible();
  });

  test('footer renders with GitHub link', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('footer')).toBeVisible();
    await expect(page.locator('footer a')).toHaveAttribute('href', 'https://github.com/owens-ben/Roomer');
  });
});

test.describe('Auth section', () => {
  test.beforeEach(async ({ page }) => {
    // Sign-in navigates to the HA instance's /auth/authorize. Stub it so the
    // tests never depend on reaching a real host (unreachable addresses make
    // the click hang until the test times out).
    await page.route(/\/auth\/authorize/, route =>
      route.fulfill({ status: 200, contentType: 'text/html', body: '<title>authorize stub</title>' }),
    );

    // Clear all stored auth before each test
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });
    await page.reload();
  });

  test('shows auth section when not authenticated', async ({ page }) => {
    await expect(page.locator('#auth-section')).toBeVisible();
    await expect(page.locator('#connected-section')).not.toBeVisible();
    await expect(page.locator('#dashboard')).not.toBeVisible();
  });

  test('sign-in button exists and is visible', async ({ page }) => {
    const btn = page.locator('#signin-btn');
    await expect(btn).toBeVisible();
    await expect(btn).toHaveText('Sign in with Home Assistant');
    await expect(btn).toBeEnabled();
  });

  test('sign-in button has click handler attached', async ({ page }) => {
    // Check that clicking the button triggers a navigation attempt
    const btn = page.locator('#signin-btn');
    await expect(btn).toBeVisible();

    // Capture any console errors
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    // Intercept the navigation to /auth/authorize so we don't actually leave
    const [request] = await Promise.all([
      page.waitForRequest(req => req.url().includes('/auth/authorize'), { timeout: 5000 }).catch(() => null),
      btn.click(),
    ]);

    if (!request) {
      // Button didn't trigger navigation — check for JS errors
      console.log('Console errors:', errors);

      // Debug: check if the listener is actually attached
      const hasListener = await page.evaluate(() => {
        const btn = document.getElementById('signin-btn');
        // getEventListeners is only in DevTools, so check via a click spy
        return btn !== null && btn instanceof HTMLElement;
      });
      expect(hasListener).toBe(true);

      // Fail with a clear message
      expect(request, 'Sign-in button click did NOT trigger navigation to /auth/authorize').not.toBeNull();
    }

    expect(request!.url()).toContain('/auth/authorize');
    expect(request!.url()).toContain('client_id=');
    expect(request!.url()).toContain('redirect_uri=');
    expect(request!.url()).toContain('state=');
  });

  test('sign-in button click sets window.location', async ({ page }) => {
    // Alternative: directly observe that clicking changes the location
    const btn = page.locator('#signin-btn');

    // Before clicking, grab current URL
    const urlBefore = page.url();

    // Listen for any navigation
    const navigationPromise = page.waitForURL(/auth\/authorize|localhost/, { timeout: 5000 }).catch(() => null);

    await btn.click();

    // Check what happened
    const urlAfter = page.url();
    const navigated = await navigationPromise;

    // Either the URL changed or a request was made
    if (urlAfter === urlBefore) {
      // Didn't navigate — debug the JS
      const debugInfo = await page.evaluate(() => {
        const btn = document.getElementById('signin-btn');
        return {
          btnExists: !!btn,
          btnTagName: btn?.tagName,
          btnType: btn?.getAttribute('type'),
          btnId: btn?.id,
          btnOnclick: btn?.getAttribute('onclick'),
          // Check if Auth object exists
          authExists: typeof (window as any).Auth !== 'undefined',
          // Try calling Auth.login manually and see what happens
          authHasLogin: typeof (window as any).Auth?.login === 'function',
        };
      });
      console.log('Debug info:', JSON.stringify(debugInfo, null, 2));
      expect.soft(debugInfo.authExists, 'Auth object should exist on window').toBe(true);
    }
  });

  test('Auth module is accessible and has login method', async ({ page }) => {
    const authInfo = await page.evaluate(() => {
      try {
        return {
          // @ts-ignore
          type: typeof Auth,
          // @ts-ignore
          hasLogin: typeof Auth?.login === 'function',
          // @ts-ignore
          hasInit: typeof Auth?.init === 'function',
          // @ts-ignore
          hasGetToken: typeof Auth?.getToken === 'function',
          // @ts-ignore
          clientId: Auth?.clientId,
          // @ts-ignore
          redirectUri: Auth?.redirectUri,
          // @ts-ignore
          haUrl: Auth?.haUrl,
        };
      } catch (e) {
        return { error: String(e) };
      }
    });

    console.log('Auth module info:', JSON.stringify(authInfo, null, 2));

    expect(authInfo).not.toHaveProperty('error');
    expect(authInfo).toHaveProperty('hasLogin', true);
    expect(authInfo).toHaveProperty('hasInit', true);
    expect(authInfo).toHaveProperty('clientId');
    expect(authInfo).toHaveProperty('redirectUri');
    expect(authInfo).toHaveProperty('haUrl');
  });

  test('Auth.login() does not throw errors (secure context fallback)', async ({ page }) => {
    // Collect any JS errors
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    const [request] = await Promise.all([
      page.waitForRequest(req => req.url().includes('/auth/authorize'), { timeout: 5000 }),
      page.locator('#signin-btn').click(),
    ]);

    expect(errors.filter(e => e.includes('Auth.login'))).toHaveLength(0);
    expect(request.url()).toContain('/auth/authorize');
  });

  test('Auth.login() navigates to HA /auth/authorize with correct params', async ({ page }) => {
    // Set the HA URL field
    await page.locator('#ha-url').fill('http://192.168.0.233:8123');

    // Intercept the navigation that Auth.login() triggers (goes to HA directly)
    const [request] = await Promise.all([
      page.waitForRequest(req => req.url().includes('/auth/authorize'), { timeout: 5000 }),
      page.locator('#signin-btn').click(),
    ]);

    const url = new URL(request.url());
    // Should navigate to HA directly, not through proxy
    expect(url.origin).toBe('http://192.168.0.233:8123');
    expect(url.pathname).toBe('/auth/authorize');
    expect(url.searchParams.has('client_id')).toBe(true);
    expect(url.searchParams.has('redirect_uri')).toBe(true);
    expect(url.searchParams.has('state')).toBe(true);
    expect(url.searchParams.get('client_id')).toBe('http://localhost:3380/');
    expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:3380/');
  });

  test('manual token form is hidden by default', async ({ page }) => {
    // The details element should be visible but collapsed
    const details = page.locator('details.manual-toggle');
    await expect(details).toBeVisible();

    // The form inside should not be visible (collapsed details)
    const form = page.locator('#manual-token-form');
    await expect(form).not.toBeVisible();
  });

  test('manual token form expands on click', async ({ page }) => {
    await page.locator('.manual-toggle summary').click();
    const form = page.locator('#manual-token-form');
    await expect(form).toBeVisible();
    await expect(page.locator('#manual-token')).toBeVisible();
  });

  test('manual token connects and shows dashboard', async ({ page }) => {
    // Expand manual token section
    await page.locator('.manual-toggle summary').click();

    // Type a token (will fail auth but we can test the UI flow)
    await page.locator('#manual-token').fill('test-token-12345');

    // Mock the API response so we don't need a real token
    await page.route('/api/states', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            entity_id: 'sensor.ben_room',
            state: 'office',
            attributes: {
              friendly_name: 'Ben Room',
              entity_type: 'person',
              confidence: 0.85,
              indicators: ['PC active', 'Motion detected'],
              raw_response: 'office',
            },
            last_changed: new Date().toISOString(),
          },
        ]),
      });
    });

    // Submit the form
    await page.locator('#manual-token-form button[type="submit"]').click();

    // Should show connected section and dashboard
    await expect(page.locator('#connected-section')).toBeVisible();
    await expect(page.locator('#dashboard')).toBeVisible();
    await expect(page.locator('#auth-section')).not.toBeVisible();

    // Auth method should show (token)
    await expect(page.locator('#auth-method')).toHaveText('(token)');

    // Token should be stored in localStorage
    const stored = await page.evaluate(() => localStorage.getItem('ha_manual_token'));
    expect(stored).toBe('test-token-12345');
  });
});

test.describe('Dashboard rendering with mocked data', () => {
  test.beforeEach(async ({ page }) => {
    // Clear auth
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });

    // Mock API
    await page.route('/api/states', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            entity_id: 'sensor.ben_room',
            state: 'office',
            attributes: {
              friendly_name: 'Ben Room',
              entity_type: 'person',
              confidence: 0.85,
              indicators: ['PC active', 'Motion detected'],
              raw_response: 'office',
            },
            last_changed: new Date().toISOString(),
          },
          {
            entity_id: 'sensor.alex_room',
            state: 'living_room',
            attributes: {
              friendly_name: 'Alex Room',
              entity_type: 'person',
              confidence: 0.72,
              indicators: ['TV playing'],
              raw_response: 'living room',
            },
            last_changed: new Date().toISOString(),
          },
          {
            entity_id: 'sensor.whiskers_room',
            state: 'bedroom',
            attributes: {
              friendly_name: 'Whiskers Room',
              entity_type: 'pet',
              confidence: 0.60,
              indicators: [],
              raw_response: 'bedroom',
            },
            last_changed: new Date().toISOString(),
          },
        ]),
      });
    });

    // Connect via manual token
    await page.reload();
    await page.locator('.manual-toggle summary').click();
    await page.locator('#manual-token').fill('mock-token');
    await page.locator('#manual-token-form button[type="submit"]').click();
    await expect(page.locator('#dashboard')).toBeVisible();
  });

  test('person cards render correctly', async ({ page }) => {
    // Wait for data to load
    await expect(page.locator('.person-card, .pet-card').first()).toBeVisible();

    const cards = page.locator('.person-card, .pet-card');
    await expect(cards).toHaveCount(3);
  });

  test('person card shows name and room', async ({ page }) => {
    await expect(page.locator('.person-card, .pet-card').first()).toBeVisible();

    // Ben should be in office — use .person-card to avoid matching room/llm cards
    const benCard = page.locator('.person-card').filter({ hasText: 'Ben' });
    await expect(benCard).toBeVisible();
    await expect(benCard.locator('.person-location')).toContainText('office');
  });

  test('confidence is said in words, with the numbers one tap down', async ({ page }) => {
    const benCard = page.locator('.person-card').filter({ hasText: 'Ben' });
    await expect(benCard.locator('.conf-word')).toHaveText('Sure');
    await expect(benCard.locator('.person-location')).toHaveText('In the office');

    // Alex is at 72%: Likely, and the sentence hedges
    const alexCard = page.locator('.person-card').filter({ hasText: 'Alex' });
    await expect(alexCard.locator('.conf-word')).toHaveText('Likely');
    await expect(alexCard.locator('.person-location')).toHaveText('Probably in the living room');

    // The percentage is inside "Why Roomer thinks so"
    await expect(benCard.locator('.confidence-text')).not.toBeVisible();
    await benCard.locator('summary').click();
    await expect(benCard.locator('.confidence-fill')).toBeVisible();
    await expect(benCard.locator('.confidence-text')).toContainText('85%');
  });

  test('clues render under Why Roomer thinks so', async ({ page }) => {
    const benCard = page.locator('.person-card').filter({ hasText: 'Ben' });
    await expect(benCard.locator('.indicator').first()).not.toBeVisible();
    await benCard.locator('summary').click();

    const indicators = benCard.locator('.indicator');
    await expect(indicators).toHaveCount(2);
    await expect(indicators.nth(0)).toBeVisible();
    await expect(indicators.nth(0)).toContainText('PC active');
    await expect(indicators.nth(1)).toContainText('Motion detected');
  });

  test('an open Why panel stays open across polls', async ({ page }) => {
    const benCard = page.locator('.person-card').filter({ hasText: 'Ben' });
    await benCard.locator('summary').click();
    await expect(benCard.locator('details')).toHaveAttribute('open', '');
    await page.waitForTimeout(5500); // one poll interval
    await expect(benCard.locator('details')).toHaveAttribute('open', '');
  });

  test('hero says who is where in a sentence', async ({ page }) => {
    await expect(page.locator('#hero-title')).toHaveText('3 home');
    const summary = page.locator('#hero-summary');
    await expect(summary).toContainText('Ben is in the office.');
    await expect(summary).toContainText('Alex is probably in the living room.');
    await expect(summary).toContainText('Whiskers is probably in the bedroom.');
  });

  test('pet card has correct styling', async ({ page }) => {
    await expect(page.locator('.pet-card').first()).toBeVisible();

    const whiskers = page.locator('.pet-card').filter({ hasText: 'Whiskers' });
    await expect(whiskers).toBeVisible();
    await expect(whiskers).toContainText('Pet');
    await expect(whiskers.locator('.person-location')).toContainText('bedroom');
  });

  test('room tiles show occupancy', async ({ page }) => {
    // Wait for rooms to update
    await page.waitForTimeout(1000);

    const officeTile = page.locator('#room-office');
    await expect(officeTile).toHaveClass(/occupied/);
    await expect(officeTile.locator('.room-status')).toContainText('Ben');

    const bedroomTile = page.locator('#room-bedroom');
    await expect(bedroomTile).toHaveClass(/occupied/);
    await expect(bedroomTile.locator('.room-status')).toContainText('Whiskers');

    const kitchenTile = page.locator('#room-kitchen');
    await expect(kitchenTile).not.toHaveClass(/occupied/);
    await expect(kitchenTile.locator('.room-status')).toContainText('Empty');

    // Everyone in a lit room is drawn as a person-coloured avatar
    await expect(officeTile.locator('.room-people .avatar')).toHaveCount(1);
    await expect(kitchenTile.locator('.room-people .avatar')).toHaveCount(0);
  });

  test('ambient mode shows the clock and the house, and exits again', async ({ page }) => {
    await page.locator('#ambient-btn').click();
    await expect(page.locator('body')).toHaveClass(/ambient/);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('#ambient-clock')).toBeVisible();
    await expect(page.locator('#ambient-people li')).toHaveCount(3);
    await expect(page.locator('#rooms-grid')).toBeVisible();
    await expect(page.locator('#persons-grid')).not.toBeVisible();
    expect(page.url()).toContain('#ambient');

    await page.keyboard.press('Escape');
    await expect(page.locator('body')).not.toHaveClass(/ambient/);
    await expect(page.locator('#persons-grid')).toBeVisible();
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.*/);
  });

  test('LLM analysis panel shows data', async ({ page }) => {
    await page.waitForTimeout(1000);

    const llm = page.locator('#llm-response');
    await expect(llm).toContainText('Ben');
    await expect(llm).toContainText('office');
    await expect(llm).toContainText('85%');
  });

  test('timeline shows initial state events', async ({ page }) => {
    await page.waitForTimeout(1000);

    const timeline = page.locator('#timeline');
    await expect(timeline.locator('.timeline-item')).toHaveCount(3); // Ben, Alex, Whiskers
  });

  test('HA status dot is online', async ({ page }) => {
    await page.waitForTimeout(1000);
    await expect(page.locator('#ha-status')).toHaveClass(/online/);
  });

  test('last update time is shown', async ({ page }) => {
    await page.waitForTimeout(1000);
    const text = await page.locator('#last-update').textContent();
    expect(text).not.toBe('--:--:--');
  });
});

test.describe('Disconnect flow', () => {
  test('disconnect button clears state and shows auth', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });

    await page.route('/api/states', route => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    await page.reload();
    await page.locator('.manual-toggle summary').click();
    await page.locator('#manual-token').fill('test-token');
    await page.locator('#manual-token-form button[type="submit"]').click();

    await expect(page.locator('#connected-section')).toBeVisible();

    // Click disconnect
    await page.locator('#disconnect-btn').click();

    // Should show auth section again
    await expect(page.locator('#auth-section')).toBeVisible();
    await expect(page.locator('#connected-section')).not.toBeVisible();
    await expect(page.locator('#dashboard')).not.toBeVisible();

    // localStorage should be cleared
    const token = await page.evaluate(() => localStorage.getItem('ha_manual_token'));
    expect(token).toBeNull();
  });
});

test.describe('OAuth callback handling', () => {
  test('code in URL triggers token exchange', async ({ page }) => {
    // Navigate first so we have access to localStorage
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });

    // Mock the token exchange endpoint
    await page.route('/auth/token', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'mock-access-token',
          refresh_token: 'mock-refresh-token',
          token_type: 'Bearer',
          expires_in: 1800,
        }),
      });
    });

    // Mock API states
    await page.route('/api/states', route => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    // Navigate with auth code
    await page.goto('/?code=mock-auth-code');

    // Should have exchanged the code and shown the dashboard
    await expect(page.locator('#connected-section')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#auth-method')).toHaveText('(OAuth)');

    // URL should be cleaned
    expect(page.url()).not.toContain('code=');

    // Refresh token stored
    const refreshToken = await page.evaluate(() => localStorage.getItem('ha_refresh_token'));
    expect(refreshToken).toBe('mock-refresh-token');
  });

  test('failed code exchange shows error', async ({ page }) => {
    // Navigate first so we have access to localStorage
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });

    await page.route('/auth/token', route => {
      route.fulfill({ status: 400, contentType: 'application/json', body: '{"error":"invalid_grant"}' });
    });

    await page.goto('/?code=bad-code');

    // Should show auth section with error
    await expect(page.locator('#auth-section')).toBeVisible();
    await expect(page.locator('#auth-error')).toBeVisible();
    await expect(page.locator('#auth-error')).toContainText('Sign-in failed');
  });

  test('stored refresh token auto-connects on reload', async ({ page }) => {
    // Pre-set a refresh token
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('ha_refresh_token', 'stored-refresh-token');
      localStorage.removeItem('ha_manual_token');
    });

    // Mock refresh endpoint
    await page.route('/auth/token', route => {
      const body = route.request().postData() || '';
      if (body.includes('grant_type=refresh_token') && body.includes('stored-refresh-token')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            access_token: 'refreshed-access-token',
            token_type: 'Bearer',
            expires_in: 1800,
          }),
        });
      } else {
        route.fulfill({ status: 401, body: 'unauthorized' });
      }
    });

    await page.route('/api/states', route => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });

    await page.reload();

    // Should auto-connect
    await expect(page.locator('#connected-section')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#auth-method')).toHaveText('(OAuth)');
  });

  test('expired refresh token shows auth section', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('ha_refresh_token', 'expired-token');
      localStorage.removeItem('ha_manual_token');
    });

    // Mock refresh failure
    await page.route('/auth/token', route => {
      route.fulfill({ status: 401, body: 'token expired' });
    });

    await page.reload();

    // Should show auth section (refresh failed)
    await expect(page.locator('#auth-section')).toBeVisible();
    await expect(page.locator('#connected-section')).not.toBeVisible();

    // Expired token should be cleared
    const token = await page.evaluate(() => localStorage.getItem('ha_refresh_token'));
    expect(token).toBeNull();
  });
});

test.describe('401 handling during polling', () => {
  test('401 on API call with token auth disconnects', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });

    let callCount = 0;
    await page.route('/api/states', route => {
      callCount++;
      if (callCount <= 1) {
        // First call succeeds
        route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      } else {
        // Second call returns 401
        route.fulfill({ status: 401, body: 'unauthorized' });
      }
    });

    // Connect via manual token
    await page.reload();
    await page.locator('.manual-toggle summary').click();
    await page.locator('#manual-token').fill('expiring-token');
    await page.locator('#manual-token-form button[type="submit"]').click();

    // Wait for the second poll to trigger 401
    await page.waitForTimeout(6000);

    // Should show auth section with error
    await expect(page.locator('#auth-section')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#auth-error')).toContainText('expired');
  });
});

test.describe('Error state: proxy not configured', () => {
  test('page still loads even if /api is unreachable', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });
    await page.reload();

    // Auth section should still show
    await expect(page.locator('#auth-section')).toBeVisible();
    await expect(page.locator('#signin-btn')).toBeEnabled();
  });
});

test.describe('Away and unsure people', () => {
  test('away people leave the house and show when they left', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ha_refresh_token');
      localStorage.removeItem('ha_manual_token');
    });
    await page.route('/api/states', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            entity_id: 'sensor.ben_room',
            state: 'kitchen',
            attributes: { friendly_name: 'Ben Room', entity_type: 'person', confidence: 0.3, indicators: [] },
            last_changed: new Date().toISOString(),
          },
          {
            entity_id: 'sensor.bob_room',
            state: 'away',
            attributes: { friendly_name: 'Bob Room', entity_type: 'person', confidence: 0.9, indicators: [] },
            last_changed: new Date().toISOString(),
          },
        ]),
      });
    });
    await page.reload();
    await page.locator('.manual-toggle summary').click();
    await page.locator('#manual-token').fill('mock-token');
    await page.locator('#manual-token-form button[type="submit"]').click();
    await expect(page.locator('#dashboard')).toBeVisible();

    await expect(page.locator('#hero-title')).toHaveText('1 home, 1 away');
    await expect(page.locator('#hero-summary')).toContainText('Ben might be in the kitchen.');
    await expect(page.locator('#hero-summary')).toContainText('Bob is away.');

    // A guess is a ghost: dashed tile, dashed avatar
    const kitchen = page.locator('#room-kitchen');
    await expect(kitchen).toHaveClass(/ghost/);
    await expect(kitchen.locator('.avatar')).toHaveClass(/t-guess/);

    // Bob is out of the house, with no confidence and no Why panel
    await expect(page.locator('#away-line')).toContainText('Bob');
    const bob = page.locator('.person-card').filter({ hasText: 'Bob' });
    await expect(bob).toHaveClass(/away/);
    await expect(bob.locator('.person-location')).toHaveText('Away');
    await expect(bob.locator('.conf-word')).toHaveCount(0);
    await expect(bob.locator('details')).toHaveCount(0);
  });
});
