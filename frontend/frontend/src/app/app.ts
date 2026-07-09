import { CommonModule, DatePipe } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Component, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { isPlatformBrowser } from '@angular/common';

type Mode = 'login' | 'signup' | 'forgot' | 'reset';

interface User {
  id: number;
  name: string;
  email: string;
}

interface Note {
  id: number;
  application_id: number;
  content: string;
  created_at: string;
}

interface JobApplication {
  id: number;
  company: string;
  job_title: string;
  status: string;
  job_link: string;
  applied_date: string;
  created_at: string;
  notes: Note[];
}

interface Resume {
  id: number;
  file_name: string;
  extracted_text: string;
  keywords: string;
  uploaded_at: string;
}

interface JobRecommendation {
  id: string;
  company: string;
  title: string;
  location: string;
  url: string;
  source: string;
  matched_keywords: string[];
  description: string;
}

interface JobRecommendationSearch {
  keywords: string[];
  location: string;
  jobs: JobRecommendation[];
}

interface AuthResponse {
  access_token: string;
  user: User;
}

interface Dashboard {
  total: number;
  by_status: Record<string, number>;
  recent_applications: JobApplication[];
  resumes: Resume[];
}

interface PasswordResetRequestResponse {
  message: string;
  email_sent: boolean;
  email_error: string | null;
}

interface MessageResponse {
  message: string;
}

@Component({
  selector: 'app-root',
  imports: [CommonModule, DatePipe, ReactiveFormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  private readonly formBuilder = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly platformId = inject(PLATFORM_ID);
  private readonly apiUrl = 'http://127.0.0.1:8010';

  protected readonly statuses = ['Saved', 'Applied', 'Interview', 'Offer', 'Rejected'];
  protected readonly mode = signal<Mode>('login');
  protected readonly token = signal<string | null>(null);
  protected readonly user = signal<User | null>(null);
  protected readonly applications = signal<JobApplication[]>([]);
  protected readonly resumes = signal<Resume[]>([]);
  protected readonly resumeKeywords = signal<string[]>([]);
  protected readonly jobRecommendations = signal<JobRecommendation[]>([]);
  protected readonly isFindingJobs = signal(false);
  protected readonly dashboard = signal<Dashboard | null>(null);
  protected readonly selectedApplicationId = signal<number | null>(null);
  protected readonly editingApplicationId = signal<number | null>(null);
  protected readonly message = signal('');
  protected readonly error = signal('');
  protected readonly busy = signal(false);

  protected readonly authForm = this.formBuilder.nonNullable.group({
    name: [''],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(6)]]
  });

  protected readonly applicationForm = this.formBuilder.nonNullable.group({
    company: ['', Validators.required],
    job_title: ['', Validators.required],
    status: ['Saved', Validators.required],
    job_link: [''],
    applied_date: [new Date().toISOString().slice(0, 10), Validators.required]
  });

  protected readonly noteForm = this.formBuilder.nonNullable.group({
    content: ['', Validators.required]
  });

  protected readonly recommendationForm = this.formBuilder.nonNullable.group({
    location: ['Remote']
  });

  protected readonly passwordResetRequestForm = this.formBuilder.nonNullable.group({
    email: ['', [Validators.required, Validators.email]]
  });

  protected readonly passwordResetConfirmForm = this.formBuilder.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
    new_password: ['', [Validators.required, Validators.minLength(6)]]
  });

  protected readonly selectedApplication = computed(() => {
    const id = this.selectedApplicationId();
    return this.applications().find((application) => application.id === id) ?? this.applications()[0] ?? null;
  });

  protected readonly statusCounts = computed(() => {
    const counts = this.dashboard()?.by_status ?? {};
    return this.statuses.map((status) => ({ status, count: counts[status] ?? 0 }));
  });

  constructor() {
    if (this.isBrowser()) {
      this.token.set(localStorage.getItem('jobTrackerToken'));
      this.user.set(this.readStoredUser());
    }

    if (this.token()) {
      this.loadWorkspace();
    }
  }

  protected setMode(mode: Mode): void {
    this.mode.set(mode);
    this.error.set('');
    this.message.set('');
  }

  protected startForgotPassword(): void {
    this.passwordResetRequestForm.patchValue({ email: this.authForm.controls.email.value });
    this.setMode('forgot');
  }

  protected requestPasswordReset(): void {
    this.error.set('');
    this.message.set('');

    if (this.passwordResetRequestForm.invalid) {
      this.passwordResetRequestForm.markAllAsTouched();
      this.error.set('Enter the email address for your account.');
      return;
    }

    this.busy.set(true);
    this.http.post<PasswordResetRequestResponse>(`${this.apiUrl}/auth/forgot-password`, this.passwordResetRequestForm.getRawValue())
      .subscribe({
        next: (response) => {
          const email = this.passwordResetRequestForm.controls.email.value;
          this.passwordResetConfirmForm.patchValue({ email });
          this.mode.set('reset');
          this.busy.set(false);
          this.message.set(response.email_error ? `${response.message} ${response.email_error}` : response.message);
        },
        error: () => {
          this.busy.set(false);
          this.error.set('Could not request a reset code.');
        }
      });
  }

  protected resetPassword(): void {
    this.error.set('');
    this.message.set('');

    if (this.passwordResetConfirmForm.invalid) {
      this.passwordResetConfirmForm.markAllAsTouched();
      this.error.set('Enter your email, 6-digit code, and a new password.');
      return;
    }

    this.busy.set(true);
    this.http.post<MessageResponse>(`${this.apiUrl}/auth/reset-password`, this.passwordResetConfirmForm.getRawValue())
      .subscribe({
        next: (response) => {
          this.busy.set(false);
          this.message.set(response.message);
          this.authForm.patchValue({
            email: this.passwordResetConfirmForm.controls.email.value,
            password: ''
          });
          this.passwordResetConfirmForm.reset();
          this.mode.set('login');
        },
        error: (err) => {
          this.busy.set(false);
          this.error.set(err.error?.detail ?? 'Could not reset your password.');
        }
      });
  }

  protected authenticate(): void {
    this.error.set('');
    this.message.set('');

    if (this.mode() === 'signup' && !this.authForm.controls.name.value.trim()) {
      this.error.set('Name is required to create an account.');
      return;
    }

    if (this.authForm.invalid) {
      this.authForm.markAllAsTouched();
      this.error.set('Enter a valid email and a password with at least 6 characters.');
      return;
    }

    const path = this.mode() === 'signup' ? '/auth/signup' : '/auth/login';
    const body = this.mode() === 'signup'
      ? this.authForm.getRawValue()
      : { email: this.authForm.controls.email.value, password: this.authForm.controls.password.value };

    this.busy.set(true);
    this.http.post<AuthResponse>(`${this.apiUrl}${path}`, body).subscribe({
      next: (response) => {
        this.writeStorage('jobTrackerToken', response.access_token);
        this.writeStorage('jobTrackerUser', JSON.stringify(response.user));
        this.token.set(response.access_token);
        this.user.set(response.user);
        this.authForm.reset();
        this.busy.set(false);
        this.message.set(`Welcome, ${response.user.name}.`);
        this.loadWorkspace();
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(err.error?.detail ?? 'Authentication failed.');
      }
    });
  }

  protected logout(): void {
    this.removeStorage('jobTrackerToken');
    this.removeStorage('jobTrackerUser');
    this.token.set(null);
    this.user.set(null);
    this.applications.set([]);
    this.resumes.set([]);
    this.dashboard.set(null);
  }

  protected saveApplication(): void {
    this.error.set('');
    if (this.applicationForm.invalid) {
      this.applicationForm.markAllAsTouched();
      this.error.set('Company, title, status, and date are required.');
      return;
    }

    const id = this.editingApplicationId();
    const request = id
      ? this.http.put<JobApplication>(`${this.apiUrl}/applications/${id}`, this.applicationForm.getRawValue(), this.headers())
      : this.http.post<JobApplication>(`${this.apiUrl}/applications`, this.applicationForm.getRawValue(), this.headers());

    this.busy.set(true);
    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.editingApplicationId.set(null);
        this.resetApplicationForm();
        this.message.set(id ? 'Application updated.' : 'Application added.');
        this.loadWorkspace();
      },
      error: () => {
        this.busy.set(false);
        this.error.set('Could not save the application.');
      }
    });
  }

  protected editApplication(application: JobApplication): void {
    this.editingApplicationId.set(application.id);
    this.applicationForm.setValue({
      company: application.company,
      job_title: application.job_title,
      status: application.status,
      job_link: application.job_link,
      applied_date: application.applied_date
    });
  }

  protected deleteApplication(id: number): void {
    this.http.delete(`${this.apiUrl}/applications/${id}`, this.headers()).subscribe({
      next: () => {
        this.message.set('Application deleted.');
        this.selectedApplicationId.set(null);
        this.loadWorkspace();
      },
      error: () => this.error.set('Could not delete the application.')
    });
  }

  protected selectApplication(id: number): void {
    this.selectedApplicationId.set(id);
  }

  protected addNote(): void {
    const application = this.selectedApplication();
    if (!application || this.noteForm.invalid) {
      this.error.set('Choose an application and enter a note.');
      return;
    }

    this.http.post<Note>(
      `${this.apiUrl}/applications/${application.id}/notes`,
      this.noteForm.getRawValue(),
      this.headers()
    ).subscribe({
      next: () => {
        this.noteForm.reset();
        this.message.set('Note added.');
        this.loadWorkspace();
      },
      error: () => this.error.set('Could not add the note.')
    });
  }

  protected deleteNote(id: number): void {
    this.http.delete(`${this.apiUrl}/notes/${id}`, this.headers()).subscribe({
      next: () => this.loadWorkspace(),
      error: () => this.error.set('Could not delete the note.')
    });
  }

  protected findRecommendedJobs(): void {
    this.error.set('');
    this.isFindingJobs.set(true);
    const location = encodeURIComponent(this.recommendationForm.controls.location.value || 'Remote');

    this.http.get<JobRecommendationSearch>(`${this.apiUrl}/job-recommendations?location=${location}`, this.headers())
      .subscribe({
        next: (response) => {
          this.resumeKeywords.set(response.keywords);
          this.jobRecommendations.set(response.jobs);
          this.isFindingJobs.set(false);
          if (!response.keywords.length) {
            this.message.set('Upload a resume with recognizable skills to improve recommendations.');
          } else if (!response.jobs.length) {
            this.message.set('No job recommendations were found for those keywords yet.');
          } else {
            this.message.set(`Found ${response.jobs.length} recommended jobs.`);
          }
        },
        error: () => {
          this.isFindingJobs.set(false);
          this.error.set('Could not load job recommendations right now.');
        }
      });
  }

  protected saveRecommendedJob(job: JobRecommendation): void {
    const today = new Date().toISOString().slice(0, 10);
    this.http.post<JobApplication>(`${this.apiUrl}/applications`, {
      company: job.company,
      job_title: job.title,
      status: 'Saved',
      job_link: job.url,
      applied_date: today
    }, this.headers()).subscribe({
      next: () => {
        this.message.set('Recommended job saved to tracker.');
        this.loadWorkspace();
      },
      error: () => this.error.set('Could not save that job to your tracker.')
    });
  }

  protected uploadResume(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    const body = new FormData();
    body.append('file', file);
    this.http.post<Resume>(`${this.apiUrl}/resumes`, body, this.headers()).subscribe({
      next: (response) => {
        input.value = '';
        this.message.set(`Resume uploaded. Detected keywords: ${response.keywords || 'none yet'}.`);
        this.resumeKeywords.set(response.keywords ? response.keywords.split(',').map((keyword) => keyword.trim()).filter(Boolean) : []);
        this.loadWorkspace();
      },
      error: () => this.error.set('Could not upload the resume.')
    });
  }

  private loadWorkspace(): void {
    this.http.get<JobApplication[]>(`${this.apiUrl}/applications`, this.headers()).subscribe({
      next: (applications) => {
        this.applications.set(applications);
        if (!this.selectedApplicationId() && applications.length) {
          this.selectedApplicationId.set(applications[0].id);
        }
      },
      error: () => this.error.set('Could not load applications. Check that the backend is running.')
    });

    this.http.get<Dashboard>(`${this.apiUrl}/dashboard`, this.headers()).subscribe({
      next: (dashboard) => {
        this.dashboard.set(dashboard);
        this.resumes.set(dashboard.resumes);
        const latestResume = dashboard.resumes[0];
        this.resumeKeywords.set(latestResume?.keywords ? latestResume.keywords.split(',').map((keyword) => keyword.trim()).filter(Boolean) : []);
      }
    });
  }

  private resetApplicationForm(): void {
    this.applicationForm.setValue({
      company: '',
      job_title: '',
      status: 'Saved',
      job_link: '',
      applied_date: new Date().toISOString().slice(0, 10)
    });
  }

  private headers(): { headers: HttpHeaders } {
    return {
      headers: new HttpHeaders({
        Authorization: `Bearer ${this.token()}`
      })
    };
  }

  private readStoredUser(): User | null {
    if (!this.isBrowser()) {
      return null;
    }

    const rawUser = localStorage.getItem('jobTrackerUser');
    return rawUser ? JSON.parse(rawUser) as User : null;
  }

  private writeStorage(key: string, value: string): void {
    if (this.isBrowser()) {
      localStorage.setItem(key, value);
    }
  }

  private removeStorage(key: string): void {
    if (this.isBrowser()) {
      localStorage.removeItem(key);
    }
  }

  private isBrowser(): boolean {
    return isPlatformBrowser(this.platformId);
  }
}
