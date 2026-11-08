package io.github.santiesc06.series76.data.auth

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** The app side of login (US-21 AC7, AC8; design U4, U6), against a local fake server. */
class AuthSessionTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val server = MockWebServer()
    private val alice = SignedInUser(email = "alice@series76.test", name = "Alice")
    private lateinit var storeScope: CoroutineScope
    private lateinit var store: DataStore<Preferences>
    private lateinit var session: AuthSession
    private lateinit var client: OkHttpClient

    @Before
    fun setUp() {
        server.start()
        openStore()
    }

    @After
    fun tearDown() {
        server.shutdown()
        storeScope.cancel()
    }

    /** Opens the token file the way the app does after a restart. */
    private fun openStore() {
        storeScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        store = PreferenceDataStoreFactory.create(scope = storeScope) {
            File(tmp.root, "auth.preferences_pb")
        }
        session = AuthSession(store)
        client = OkHttpClient.Builder().addInterceptor(AuthInterceptor(session)).build()
        runBlocking { session.restore() }
    }

    private fun restart() {
        storeScope.cancel()
        openStore()
    }

    private fun call(code: Int = 200, authorization: String? = null): String? {
        server.enqueue(MockResponse().setResponseCode(code))
        val request = Request.Builder().url(server.url("/api/sessions"))
            .apply { if (authorization != null) header("Authorization", authorization) }
            .build()
        client.newCall(request).execute().close()
        return server.takeRequest().getHeader("Authorization")
    }

    @Test
    fun `signed in requests carry the bearer token`() = runBlocking { // US-21 AC7, design U4
        session.signIn("tok-1", alice)
        assertEquals("Bearer tok-1", call())
    }

    @Test
    fun `signed out requests carry no token and a 401 is not an expired session`() {
        assertEquals(AuthState.SignedOut(), session.state.value) // nothing saved yet
        assertNull(call(code = 401)) // e.g. a wrong password on the login screen
        assertEquals(AuthState.SignedOut(expired = false), session.state.value)
    }

    @Test
    fun `a 401 to the current token returns to login as expired`() = runBlocking { // US-21 AC7
        session.signIn("tok-1", alice)
        call(code = 401)
        assertEquals(AuthState.SignedOut(expired = true), session.state.value)
        assertNull(session.token)
    }

    @Test
    fun `a late 401 for an old token does not sign out the new session`() = runBlocking {
        session.signIn("old", alice)
        session.signIn("new", alice)
        session.onUnauthorized("old")
        assertEquals(AuthState.SignedIn(alice), session.state.value)
        assertEquals("Bearer new", call())
    }

    @Test
    fun `a request that already has a token keeps it`() = runBlocking { // logout, design U1
        session.signIn("new", alice)
        assertEquals("Bearer old", call(authorization = "Bearer old"))
    }

    @Test
    fun `the token survives an app restart`() = runBlocking { // US-21 AC7
        session.signIn("tok-1", alice)
        restart()
        assertEquals(AuthState.SignedIn(alice), session.state.value)
        assertEquals("Bearer tok-1", call())
    }

    @Test
    fun `logout forgets the token at once and on disk`() = runBlocking { // US-21 AC8
        session.signIn("tok-1", alice)
        session.signOut()
        assertNull(call())
        withTimeout(5_000) { store.data.first { it[stringPreferencesKey("token")] == null } }
        restart()
        assertEquals(AuthState.SignedOut(), session.state.value)
    }
}
